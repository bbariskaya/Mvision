Face Recognition API
Video – Ek Gereksinimler

Giriş

Bu doküman, tek görüntü üzerinden çalışan mevcut yüz tanıma servisinin video inputlarını da işleyebilecek şekilde genişletilmesini kapsar. Sistem, kendisine gönderilen bir videoyu kareler (frame) halinde işler, her karedeki yüzleri tespit eder, mevcut tanıma mantığıyla (known / anonymous / new_anonymous) kimliklendirir ve ardışık karelerde aynı kişiyi tutarlı biçimde takip eder. Çıktı, kare kare değil; videoda görünen kişiler bazında özetlenir. Böylece istemci, bir videoda kimlerin bulunduğunu, her kişinin ne zaman ve ne kadar süre göründüğünü net olarak görebilir.

Mevcut izlenebilirlik katmanı (process ID, loglama, geçmiş sorgulama) korunur ve video bağlamına genişletilir: her video işlemi bir işe (job) bağlanır, video metadata'sı (süre, fps, kare sayısı) loglanır ve bir yüzün hangi videonun hangi anında göründüğü geriye dönük sorgulanabilir.

Mevcut görüntü tabanlı tüm gereksinimler geçerliliğini korur; bu doküman yalnızca video inputuna özgü ek gereksinimleri tanımlar. Canlı akış (RTSP, webcam vb.) bu sürümün kapsamı dışındadır ancak mimari ileride bu girdi tipine genişletilebilecek şekilde tasarlanmalıdır.

1. Video Input
    • API, request içerisinde bir video kabul edebilmeli
    • Videonun geçerli/desteklenen bir formatta olduğu doğrulanmalı (örn. mp4, avi, mov).
    • Video okunamıyor, bozuk veya boş ise anlamlı bir hata dönülmeli.
    • Videoda hiç yüz bulunamadığı durum hata değil; ayrı bir sonuç ("yüz bulunamadı") olarak ele alınmalı.
    • Maksimum dosya boyutu ve/veya süre limiti tanımlanmalı; limit aşıldığında net bir hata dönülmeli.
    • Gönderilen input video, belirlenen bir saklama süresi (retention) boyunca sistemde tutulmalı; bu süre sonunda otomatik olarak silinmeli.
    • Saklama süresi ve saklama yolu/dizini yapılandırılabilir olmalı (environment variable).
    • Saklanan videoya, ilgili job/process ID üzerinden erişilebilmeli (örn. sonradan yeniden işleme veya doğrulama için).
    • Bu limitler (boyut, süre, desteklenen formatlar, saklama süresi) yapılandırılabilir olmalı (environment variable).
2. Frame Çıkarma / Örnekleme (Sampling)
    • Videodan işlenecek kareler bir örnekleme stratejisine göre seçilmeli (örn. her N karede bir veya saniyede X kare).
    • Örnekleme oranı, request parametresi ve/veya environment variable ile dışarıdan ayarlanabilmeli.
    • Her işlenen kare için video içi zaman bilgisi (timestamp / saniye ve kare numarası) tutulmalı.
    • Her karenin işlenmesi, mevcut tek görüntü tanıma mantığıyla aynı kurallara tabi olmalı (detection + recognition).
3. Face Tracking
    • Ardışık karelerde görünen aynı yüz takip edilmeli ve aynı kişiye bir track ID atanmalı.
    • Track ID, mevcut kalıcı face ID ile ilişkilendirilmeli: tracking "karelerdeki bu yüz aynı obje mi", recognition "bu obje kim" sorusunu cevaplamalı.
    • Bir track boyunca karelerde farklı tanıma sonuçları çıkarsa (kimi karede known, kimi anonymous), güven/çoğunluk bazlı tek bir nihai karara bağlanmalı.
4. Sonuç Toplama (Aggregation)
    • Çıktı kare kare değil; video içinde görünen benzersiz kişiler (track/face ID) bazında özetlenmeli.
    • Her kişi için en az: ilk göründüğü an, son göründüğü an, toplam görünme süresi ve göründüğü kare/zaman aralıkları dönülmeli.
    • Özet bilgisine ek olarak, her kişi için işlenen her karedeki bbox detayı da dönülmeli: kare numarası, video içi timestamp ve o karedeki bounding box. Bu detay, istemcinin video üzerine bbox çizebilmesi için gereklidir.
    • Her kişi için mevcut tanıma alanları korunmalı: faceId, status (known / anonymous / new_anonymous), name (yalnızca known'da dolu), metadata, confidence.
    • Videoda hem bilinen hem anonim kişiler aynı anda bulunabilmeli ve her biri ayrı sonuçlanmalı.
    • İlk kez görülen yüzler için mevcut new_anonymous mantığı işlemeli; bu anonim kayıtlar veritabanına eklenmeli ve sonraki videolarda aynı yüz tekrar gelirse aynı ID ile tanınmalı.
5. Bounding Box ve Koordinat Sistemi
    • Sistem performans için videoyu küçülterek (downscale) işleyebilir; ancak dönülen tüm bounding box koordinatları orijinal video çözünürlüğüne göre verilmeli.
    • Yani işleme sırasında ölçekleme yapılsa bile, koordinat dönüşümü API tarafında yapılmalı; istemci herhangi bir ölçekleme/oran düzeltmesi yapmak zorunda kalmamalı.
    • Bounding box, istemcinin doğrudan orijinal video karesi üzerine çizebileceği şekilde dönülmeli (örn. x, y, width, height ya da sol/üst/sağ/alt köşe koordinatları net tanımlanmalı).
6. Asenkron İşlem / Job Yönetimi
    • Video işleme uzun sürebileceğinden, işlem asenkron yürütülmeli: istek anında bir job ID dönülmeli, sonuç hemen beklenmemeli.
    • Job durumu sorgulanabilmeli: pending / processing / completed / failed ve mümkünse ilerleme yüzdesi.
    • İşlem tamamlandığında sonuç ayrı bir çağrı ile alınabilmeli.
    • Bir job'un iptal edilebilmesi desteklenmeli.
7. İşlem Takibi ve Loglama
    • Mevcut process ID ve loglama mantığı korunmalı; her video işlemi bir process/job ile ilişkilendirilmeli.
    • Process detayına video metadata'sı eklenmeli: video süresi, fps, toplam kare sayısı ve işlenen kare sayısı.
    • Task detayı en az: işlem tipi (video), işlenen kişi sayısı, tespit edilen face ID'ler ve status bilgilerini içermeli.
    • Loglar kalıcı olarak saklanmalı ve sorgulanabilir olmalı; loglama ana işlemin başarısını engellememeli.
8. Geçmiş / İlişki Sorgulama (Genişletme)
    • Belirli bir face ID'nin daha önce hangi videolarda ve o videoların hangi anlarında (timestamp) göründüğü sorgulanabilmeli.
    • Sonuç; ilgili process/job ID'leri, video referansları ve zaman bilgilerini içermeli.
    • Belirli bir job ID'ye ait video sonucunun ve detaylarının geri çağrılması mümkün olmalı.
9. API Davranışı
    • Sadece API olarak çalışmalı; herhangi bir kullanıcı arayüzü olmayacak.
    • Her yeni endpoint için input/output contract'ı tanımlanmalı.
    • Cevaplar yapısal ve tutarlı bir formatta dönülmeli (örn. job ID + kişi listesi + her kişi için faceId, status, isim, görünme zamanları, kare bazlı kutu detayları, skor).
    • Hata durumları standart ve ayırt edilebilir şekilde raporlanmalı.
    • Video sonuç formatı, mevcut görüntü sonuç formatıyla uyumlu/tutarlı olmalı.
10. Örnek API Endpoint'leri
    • POST /videos/recognize – Gönderilen videoyu işlemek üzere bir job oluşturur ve job ID döner.
    • GET /videos/jobs/{jobId} – Bir job'un durumunu (pending / processing / completed / failed) ve ilerlemesini döner.
    • GET /videos/jobs/{jobId}/result – Tamamlanmış bir job'un kişi bazlı sonucunu (faceId, status, isim, görünme zamanları, skor) döner.
    • DELETE /videos/jobs/{jobId} – Devam eden bir job'u iptal eder.
    • GET /faces/{faceId}/appearances – Bir face ID'nin hangi videolarda ve hangi anlarda göründüğünü döner.
11. Sonuç İçeriği
Her işlenmiş video için: job/process ID, video metadata'sı (süre, fps, çözünürlük, işlenen kare sayısı) ve tespit edilen benzersiz kişi sayısı.
Her kişi için:
    • faceId – her zaman dolu (anonim de olsa).
    • trackId – kişinin video içindeki takip kimliği.
    • status – known / anonymous / new_anonymous.
    • name – yalnızca known durumunda dolu, diğerlerinde null.
    • metadata – kayıtlı kişiye ait ek bilgiler (varsa), anonimde boş.
    • firstSeen / lastSeen – kişinin videoda ilk ve son görüldüğü an.
    • appearances – kişinin göründüğü zaman aralıkları (başlangıç/bitiş timestamp ve kare bilgisi).
    • detections – kişinin işlenen her karedeki detayı; her biri: frame numarası, timestamp ve orijinal çözünürlüğe göre boundingBox. İstemci bu listeyi kullanarak video üzerine kutu çizebilir.
    • confidence – nihai eşleşme güven skoru.
12. Örnek Response (JSON)
Aşağıdaki örnek, tamamlanmış bir video işleme job'unun sonucunu (GET /videos/jobs/{jobId}/result) temsil eder. Alan adları ve yapı bilgilendirme amaçlıdır; nihai contract uygulamada netleştirilmelidir. Bounding box koordinatları orijinal video çözünürlüğüne göredir.

{
  "jobId": "job_8f3c1a2e",
  "processId": "proc_5d9b7c10",
  "status": "completed",
  "video": {
    "duration": 42.5,
    "fps": 30,
    "width": 1920,
    "height": 1080,
    "totalFrames": 1275,
    "processedFrames": 128,
    "samplingRate": "every_10th_frame"
  },
  "personCount": 2,
  "persons": [
    {
      "faceId": "face_001",
      "trackId": "track_a1",
      "status": "known",
      "name": "Ahmet Yilmaz",
      "metadata": { "department": "Engineering" },
      "firstSeen": 1.2,
      "lastSeen": 12.8,
      "totalDuration": 11.6,
      "confidence": 0.94,
      "appearances": [
        { "start": 1.2, "end": 12.8, "startFrame": 36, "endFrame": 384 }
      ],
      "detections": [
        {
          "frame": 36,
          "timestamp": 1.2,
          "boundingBox": { "x": 640, "y": 220, "width": 180, "height": 180 },
          "confidence": 0.93
        },
        {
          "frame": 46,
          "timestamp": 1.53,
          "boundingBox": { "x": 648, "y": 224, "width": 182, "height": 181 },
          "confidence": 0.95
        }
      ]
    },
    {
      "faceId": "face_117",
      "trackId": "track_b2",
      "status": "new_anonymous",
      "name": null,
      "metadata": {},
      "firstSeen": 3.0,
      "lastSeen": 9.4,
      "totalDuration": 6.4,
      "confidence": 0.81,
      "appearances": [
        { "start": 3.0, "end": 9.4, "startFrame": 90, "endFrame": 282 }
      ],
      "detections": [
        {
          "frame": 90,
          "timestamp": 3.0,
          "boundingBox": { "x": 1100, "y": 300, "width": 160, "height": 160 },
          "confidence": 0.80
        }
      ]
    }
  ]
}

13. Performans ve Ölçeklenme
    • Frame işleme paralel/batch olarak yürütülebilmeli (örn. kuyruk + worker mimarisi).
    • Eşzamanlı job sayısı, timeout ve kaynak limitleri yapılandırılabilir olmalı.
    • Örnekleme oranı, sistemin makul sürede yanıt verebilmesi için ayarlanabilir tutulmalı.
14. Deployment – Docker
    • Video işleme bileşeni mevcut API ile birlikte Docker üzerinde çalışabilecek şekilde paketlenmeli.
    • Ayrı bir worker servisi gerekiyorsa, tüm sistem docker-compose ile tek seferde ayağa kaldırılabilmeli.
    • Tüm yapılandırılabilir parametreler (örnekleme oranı, eşik değeri, dosya/süre limitleri, video saklama süresi ve yolu, veri yolu, port, eşzamanlı job sayısı, timeout vb.) environment variable ile dışarıdan verilebilmeli; kod içinde sabit (hard-coded) değer bulunmamalı.
    • İşlenen videolara, job sonuçlarına ve anonim kayıtlara ait kalıcı veriler container yeniden başlatıldığında kaybolmamalı.
