# Phase 1 — Referans Implementasyon Analizi

## Amaç

Tek görüntü üzerinde:

1. Yüz tespiti (detection)
2. 5 noktalı yüz landmark’ı çıkarımı
3. Landmark bazlı GPU hizalama (alignment)
4. ArcFace ile embedding çıkarımı

işlemlerini DeepStream / GStreamer pipeline’ında, mümkün olduğunca GPU’da tutarak gerçekleştirmek.

Bu analizde referans olarak incelediğimiz iki açık kaynak proje detaylıca anlatılır:

- `marcoslucianops/DeepStream-Yolo-Face`
- `zhouyuchong/face-recognition-deepstream` (+ `zhouyuchong/gst-nvinfer-custom`)

---

## Kullanılan Modeller

### Yüz Tespiti — YOLOv8-Face

- Kaynak: `derronqi/yolov8-face`
- ResNet / CSPDarknet tabanlı YOLOv8 mimarisi, WIDERFace üzerinde eğitilmiş.
- Çıktı: her yüz için `[x1, y1, x2, y2, confidence, kpt1_x, kpt1_y, …, kpt5_x, kpt5_y]` — toplam 15 değer.
- Dinamik batch desteği için ONNX export şöyle yapılır:

```bash
python3 export_yoloV8_face.py -w yolov8n-face.pt --dynamic
```

Bu flag ile ONNX input axes `[batch, 3, height, width]` ve output axes dinamik hale gelir. DeepStream `streammux.batch-size` ve `batch-size` parametreleriyle aynı anda birden fazla frame beslenebilir.

### Yüz Tanıma — ArcFace

- Kaynak: `deepinsight/insightface` — Glint360k üzerinde eğitilmiş R50/R100
- Girdi: 112×112 hizalanmış yüz
- Çıktı: 512 boyutlu L2-normalize edilmiş embedding

---

## 1. `DeepStream-Yolo-Face`: PGIE + Landmark Çıkarımı

### Genel Akış

```
decode → nvstreammux → nvinfer(PGIE YOLOv8-Face) → nvtracker → ...
```

PGIE’nin görevi yalnızca yüz bbox’larını ve 5 landmark’ı üretmektir. Nasıl yaptığına bakalım.

### 1.1 Config (Primary GIE)

`config_infer_primary_yoloV8_face.txt`:

```ini
[property]
gpu-id=0
process-mode=1
network-mode=2                    # FP16
gie-unique-id=1
network-type=0                    # detection
parse-bbox-func-name=NvDsInferParseYoloFace
custom-lib-path=.../libnvdsinfer_custom_impl_Yolo.so
num-detected-classes=1
cluster-mode=4                    # custom parser kendi NMS’ini yapar
maintain-aspect-ratio=1
symmetric-padding=1
batch-size=16
output-tensor-meta=0

enable-output-landmark=1          # zhouyuchong patch’lenmiş nvinfer için gerekli
```

`parse-bbox-func-name` ve `custom-lib-path` ile DeepStream’a "çıktıyı benim parser’ım çözümleyecek" denir.

### 1.2 Custom Parser (`nvdsparseface_Yolo.cpp`)

Parser’ın imzası:

```cpp
extern "C" bool NvDsInferParseYoloFace(
    const std::vector<NvDsInferLayerInfo>& outputLayersInfo,
    const NvDsInferNetworkInfo& networkInfo,
    const NvDsInferParseDetectionParams& detectionParams,
    std::vector<NvDsInferInstanceMaskInfo>& objectList);
```

`NvDsInferInstanceMaskInfo`, normal `NvDsObjectMeta`’nın bir uzantısıdır ve `mask` pointer’ı ile ek veri taşımaya izin verir. Parser şunları yapar:

1. Model çıktısındaki her aday kutuyu (anchor) dolaşır.
2. Confidence threshold kontrolü yapar.
3. Geçen adaylar için `addBBoxProposal(...)` ile bbox’u doldurur.
4. Ardından `addFaceProposal(...)` ile 5 landmark’ı `b.mask` pointer’ına yazar.

`addFaceProposal` içindeki temel işlem:

```cpp
size_t landmarksSize = 15;  // 5 nokta * 3 (x, y, visibility)
b.mask = new float[landmarksSize];
for (size_t p = 0; p < 5; ++p) {
    b.mask[p * 3 + 0] = clamp(output[... + p * 2 + 5], 0, netW);
    b.mask[p * 3 + 1] = clamp(output[... + p * 2 + 6], 0, netH);
    b.mask[p * 3 + 2] = 1.0;  // visibility
}
b.mask_width  = netW;
b.mask_height = netH;
b.mask_size   = sizeof(float) * landmarksSize;
```

### 1.3 NMS

Parser kendi içinde basit bir NMS uygular:

```cpp
static std::vector<NvDsInferInstanceMaskInfo>
nonMaximumSuppression(std::vector<NvDsInferInstanceMaskInfo> binfo);
```

Özetle `cluster-mode=4` seçiliyken DeepStream clustering devre dışı kalır; parser çıktıyı son halde verir.

### 1.4 Landmark’ların Yeri

Bu aşamada landmark’lar `NvDsInferInstanceMaskInfo.mask` içindedir. DeepStream standart `nvinfer` bunu `obj_meta.mask_params` olarak iletir. Fakat standart `nvinfer`, SGIE’nin (ikinci inference) bu landmark’ları kullanmasını sağlayacak bir mekanizma sunmaz. İşte bu noktada `gst-nvinfer-custom` devreye girer.

---

## 2. `gst-nvinfer-custom`: nvinfer Plugin Patch’i

### Neden Patch?

Standart DeepStream `nvinfer` plugin’i şunları yapamaz:

- Detection çıktısındaki landmark’ları obje meta’ya özel bir alan olarak taşımak.
- SGIE seviyesinde bbox crop yerine landmark bazlı affine transformla hizalama yapmak.
- `network-type=100` gibi özel bir recognizer tipini tanımak.

`zhouyuchong/gst-nvinfer-custom`, `libnvdsgst_infer.so` ve `libnvds_infer.so` dosyalarını yeniden derleyerek şu özellikleri ekler:

1. Detection sonrası landmark’ları `obj_meta->obj_user_meta_list` içine ekler.
2. Classifier (SGIE) çalışmadan önce bu landmark’ları okur.
3. NPP + OpenCV tabanlı benzerlik transformu ile yüzü 112×112’ye hizalar.
4. Sonra normal `nvinfer` inference akışına devam eder.

### Kurulum

```bash
git clone https://github.com/zhouyuchong/gst-nvinfer-custom.git
cd gst-nvinfer-custom
sh install.sh
```

`install.sh`, sistemdeki orijinal `nvinfer` kütüphanelerini `./backup` altına yedekler ve custom derlenmiş `.so` dosyalarını yerleştirir.

### Nasıl Çalışır?

`README.md`’deki özeti:

#### Detector tarafı

1. Custom parser (`nvdsinfer_customparser`) çıktıyı çözerken `oinfo.numLmks` ve `oinfo.landmarks` alanlarını doldurur.
2. `DetectPostprocessor::fillUnclusteredOutput` fonksiyonu modifiye edilmiştir; landmark bilgisi labelların sonuna eklenir.
3. `attach_metadata_detector` aşamasında landmark’lar decode edilip `obj_user_meta_list`’e yazılır.

#### Classifier tarafı

1. SGIE çalışmadan önce `obj_user_meta_list`’teki landmarklar okunur.
2. Landmark bazlı NPP alignment uygulanır.
3. ArcFace inference çalışır.

### Config Değişiklikleri

Detector config:

```ini
cluster-mode=4
enable-output-landmark=1
```

Classifier config:

```ini
network-type=100
alignment-type=1
# alignment-type=1 -> ArcFace, 112x112
# alignment-pics-path=/path/to/save/debug/aligned/images
```

---

## 3. Alignment Matematiği

`gst-nvinfer-custom/gst-nvinfer/align_functions.cpp`

### ArcFace Standart 5 Noktası

```cpp
float standard_face[5][2] = {
    {38.2946f, 51.6963f},  // sol göz
    {73.5318f, 51.5014f},  // sağ göz
    {56.0252f, 71.7366f},  // burun ucu
    {41.5493f, 92.3655f},  // sol ağız köşesi
    {70.7299f, 92.2041f}   // sağ ağız köşesi
};
```

Bu koordinatlar 112×112 görüntü içinde ArcFace’in beklediği referans noktalardır.

### Benzerlik Transformu

Kaynak landmark’lar (`dst`) ile hedef noktalar (`src`) arasında **similarity transform** (ölçek + dönme + öteleme) hesaplanır. Temel yöntem:

1. Her iki nokta setinin merkezini (mean) hesapla ve orijine taşı.
2. Varyans / ortalama uzaklık ile ölçek faktörünü bul.
3. SVD kullanarak en iyi dönme matrisini hesapla.
4. 2×3 affine matris oluştur.

`SimilarTransform` fonksiyonunda Umeyama yöntemi kullanılır.

### Warp

Affine matris hesaplandıktan sonra:

- OpenCV: `cv::warpAffine(...)` ile CPU üzerinde 112×112’ye çevrilebilir.
- NPP: `nppiWarpAffine_8u_C3R` / `nppiWarpAffine_32f_C3R` ile GPU üzerinde çevrilebilir.

`gst-nvinfer-custom`’da NPP tercih edilir, böylece görüntü GPU’da kalır.

---

## 4. `face-recognition-deepstream`: Tam Pipeline

### Pipeline Elemanları

`config/config_pipeline.toml` ve `main.py`’den:

```
source → nvstreammux → queue → pgie
pgie → queue → tracker → queue → sgie
sgie → queue → tiler → queue → nvvidconv
nvvidconv → queue → nvosd → queue → sink
```

PGIE: YOLOv8-Face  
Tracker: NvDCF / IOU  
SGIE: ArcFace (custom nvinfer ile alignment)  

### PGIE Probe

`pgie_src_filter_probe`:

```python
def pgie_src_filter_probe(pad, info, u_data):
    batch_meta = pyds.gst_buffer_get_nvds_batch_meta(hash(gst_buffer))
    # frame bazında obje meta dolaşılır
    # confidence < 0.6 olan yüzler kaldırılır
```

Bu probe PGIE çıkışında çalışır; düşük confidence yüzleri frame’den siler.

### SGIE Probe

`sgie_feature_extract_probe`:

```python
def sgie_feature_extract_probe(pad, info, data):
    loaded_faces = data[0]
    # obj_meta.obj_user_meta_list içinde NVDSINFER_TENSOR_OUTPUT_META ara
    # 512 elemanlı embedding çıkar
    # L2 normalize et
    # Bilinen yüzlerle dot-product (cosine similarity) hesapla
    # Eşik üzerindeyse display_meta ile isim yaz
```

`get_face_feature` fonksiyonu:

```python
layer = pyds.get_nvds_LayerInfo(tensor_meta, 0)
output = []
for i in range(512):
    output.append(pyds.get_detections(layer.buffer, i))
res = np.reshape(output, (1, -1))
norm = np.linalg.norm(res)
normal_array = res / norm
```

Bu referans probe, tanıma mantığını GPU pipeline çıkışında, CPU üzerinde yapar.

---

## 5. Dynamic Batch Nasıl Çalışır?

YOLOv8-Face ONNX export’unda `--dynamic` ile:

- Input: `[N, 3, 640, 640]`
- Output: dinamik batch + toplam anchor sayısı veya feature map dimleri dinamik olabilir

DeepStream tarafında:

- `streammux`’ün `batch-size` = aynı anda pipeline’a giren frame sayısı.
- PGIE `batch-size` = bir inference adımında işlenecek maksimum frame sayısı.
- `nvinfer` otomatik olarak aynı batch’ten çıkan her yüzü obje meta olarak işaretler.
- `gst-nvinfer-custom` da multi-batch desteklidir; her frame için ayrı landmark ve alignment uygulanır.

Sonuç: tek image endpoint için `batch-size=1`, video / çoklu stream için `batch-size>1` ayarlanarak aynı model ve kod kullanılabilir.

---

## 6. İki Yaklaşımın Karşılaştırması

| Konu | `DeepStream-Yolo-Face` | `zhouyuchong/face-recognition-deepstream` |
|---|---|---|
| Detector | YOLOv5/7/8-Face | YOLOv8-Face / RetinaFace |
| Landmark saklama | `mask_params` | `obj_user_meta_list` (patch sonrası) |
| Alignment | Yok (sadece bbox crop) | `gst-nvinfer-custom` NPP alignment |
| Recognition | Yok | ArcFace |
| Derinlik | Detection katmanı | Full pipeline |
| Risk | Düşük (standart API) | Orta-yüksek (nvinfer patch) |
| Bakım | Kolay | Derinstream güncellemelerinde zor |

---

## 7. Kendi Implementasyonumuza Alacağımız Dersler

### Ne doğrudan kullanacağız?

- `DeepStream-Yolo-Face` custom parser’ın **landmark’ları obje meta’ya bağlama fikri**.
- `zhouyuchong/utils/probe.py`’deki **embedding çıkarma ve cosine similarity** örüntüsü.
- `align_functions.cpp`’teki **ArcFace referans noktaları ve Umeyama benzerlik transformu**.

### Ne kendimiz yazacağız?

- PGIE parser: YOLOv8-Face output’un kendi modelimize göre decode’u (örneğin 3 feature map + DFL).
- Alignment: `nvdspreprocess` custom `.so` içinde landmark okuma + affine matrix + CUDA/NPP warp.
- ArcFace SGIE config ve TensorRT engine oluşturma.
- Probe: CPU tarafında embedding’i alıp FastAPI + Qdrant + PostgreSQL işlemlerine yönlendirme.
- Docker compose: FastAPI, pipeline service, PostgreSQL, Qdrant, MinIO.

### Neden `gst-nvinfer-custom` patch’ini kullanmıyoruz?

- DeepStream 7.1 + CUDA 13 ortamında orijinal plugin’leri değiştirmek derleme ve uyumluluk riski taşır.
- `nvdspreprocess` custom library standart DeepStream API’sidir; upgrade’lerden etkilenme olasılığı düşüktür.
- Modüler kalıp detection, alignment, recognition adımlarını bağımsız test edebiliriz.

---

## Kaynak Dosyalar

```
tmp/DeepStream-Yolo-Face/
  ├─ nvdsinfer_custom_impl_Yolo_face/nvdsparseface_Yolo.cpp
  ├─ config_infer_primary_yoloV8_face.txt
  └─ docs/YOLOv8_Face.md

tmp/face-recognition-deepstream/
  ├─ config/config_yolov8n_face.txt
  ├─ config/config_arcface.txt
  ├─ config/config_pipeline.toml
  ├─ main.py
  ├─ utils/probe.py
  └─ README.md

tmp/gst-nvinfer-custom/
  ├─ gst-nvinfer/align_functions.cpp
  ├─ gst-nvinfer/align_functions.h
  ├─ install.sh
  └─ README.md
```
