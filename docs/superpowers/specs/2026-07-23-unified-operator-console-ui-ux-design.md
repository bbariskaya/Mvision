# Birleşik Operatör Konsolu UI/UX Tasarımı

## 1. Amaç

Mevcut InterProbe operatör konsolunu Phase 1 görüntü tanıma, Phase 2 asenkron video işleme ve Phase 3 çok kameralı canlı yayın operasyonlarını tek bir masaüstü uygulamasında birleştirecek şekilde genişletmek.

Konsol aşağıdaki backend teslimatlarının operatör yüzüdür:

- `2026-07-23-phase1-phase2-requirements-compliance.md`
- `2026-07-23-live-session-mediamtx-ingress.md`
- `2026-07-23-live-frame-json-appearance.md`
- `2026-07-23-optional-live-media-outputs.md`
- `2026-07-23-isolated-multi-camera.md`

UI bu backend sözleşmelerini tüketir; kimlik birleştirme, media orchestration, retry, lease, connector delivery veya recording reconciliation gibi business logic'i tarayıcıda yeniden uygulamaz.

## 2. Kullanıcı ve Erişim Modeli

- Sistem yalnızca şirket içi ağda kullanılacaktır.
- Ağa ulaşabilen herkes tam operatör yetkisine sahiptir.
- Login, kullanıcı hesabı, rol veya yetki matrisi eklenmeyecektir.
- Phase 3 yönetim endpoint'lerinin API anahtarı tarayıcıya verilmez.
- Nginx/reverse proxy, yalnızca izin verilen `/api/v1/live/*` yönetim isteklerine backend API anahtarını server-side ekler.
- Internal recording-hook endpoint'i, connector secret'ları ve MediaMTX Control API UI üzerinden erişilebilir değildir.

Bu erişim modeli public internet güvenlik modeli değildir. Şirket ağı sınırı, reverse proxy erişim kuralı ve backend secret yönetimi release önkoşuludur.

## 3. Kapsam

### 3.1 Dahil

- Görüntü tanıma, tek yüz enrollment ve sonuç overlay'i.
- Kimlik bulma, güncelleme, deactivate etme ve geçmiş inceleme.
- Process bulma, immutable sonuç ve event trace inceleme.
- Video yükleme, sampling ayarı, job polling, iptal ve hata inceleme.
- Kaynak video playback, timestamp-senkron bbox ve kişi zaman çizelgesi.
- Canlı session listesi, kapasite görünümü ve kılavuzlu session oluşturma.
- Session reconfigure/stop ve generation/run sağlık görünümü.
- Annotated WebRTC/WHEP playback.
- Frame-result, appearance, connector, recording ve public output görünümü.
- Delivery 4 sonrasında izole multi-camera grid görünümü.
- Türkçe kullanıcı metinleri.

### 3.2 Hariç

- Public veya internet-facing authentication.
- Rol tabanlı yetkilendirme.
- UI içinde secret tekrar gösterimi.
- Backend'de olmayan global video-job listeleme veya analytics endpoint'i.
- Arbitrary SQL/PromQL/LogQL editörü.
- Connector delivery garantisini UI tarafında değiştirmek.
- Raw embedding, aligned face bytes veya internal media path gösterimi.
- Mobilde işlevsel operatör deneyimi.
- Exact recording-frame join veya annotated recording.

## 4. Tasarım İlkeleri

1. **Durable backend state gerçeğin kaynağıdır.** UI local optimistic state'i kalıcı gerçek gibi göstermez.
2. **Bir kimlik bütün fazlarda aynıdır.** Aynı `faceId`, görüntü, video ve live appearance'ları arasında doğrudan gezilebilir.
3. **Kontrol ve media birbirinden bağımsızdır.** Playback hatası session kontrolünü; connector hatası inference görünümünü kilitlemez.
4. **Secret write-only'dir.** Kaynak URI ve auth bilgileri submit sonrasında DOM'a geri dönmez.
5. **Yoğunluk kontrollüdür.** Genel kabuk açık ve sakin, live detail alanı gerektiği kadar yoğun olur.
6. **Sahte global veri yoktur.** Backend list endpoint'i yoksa UI yalnızca current-browser recent history veya doğrudan ID lookup sunar.
7. **Her asenkron işin durumu görünürdür.** Loading, stale, empty, cancelling, failed ve terminal durumlar birbirinden ayrılır.

## 5. Görsel Dil

Mevcut InterProbe kimliği korunur:

- Logo recolor, crop veya yeniden çizim olmadan kullanılır.
- Ana renkler deep navy, signal green ve warm off-white'dır.
- Manrope arayüz metninde, Newsreader sınırlı editorial vurgu için, JetBrains Mono ID, timestamp ve telemetry için kullanılır.
- Generic mavi SaaS kartları, neon cyberpunk, glassmorphism ve dekoratif gradient yoğunluğu kullanılmaz.
- Live media yüzeyleri koyu olabilir; navigasyon ve kayıt ekranları mevcut açık yüzey dilini sürdürür.
- Status yalnızca renkle anlatılmaz; ikon, label ve gerektiğinde açıklama birlikte kullanılır.

## 6. Ekran Boyutu Politikası

- Desteklenen minimum viewport: `1280x720`.
- Daha dar viewport'ta uygulama business route'larını render etmez.
- `DesktopGuard`, Türkçe bir desteklenmeyen cihaz mesajı, minimum çözünürlük ve operatör iletişim yönlendirmesi gösterir.
- Desteklenen masaüstünde klavye navigasyonu, görünür focus ve reduced-motion desteği zorunludur.

## 7. Bilgi Mimarisi

Sol rail iki gruba ayrılır.

### Operasyon

- Genel Bakış
- Görüntü
- Video
- Canlı

### Kayıtlar

- Kimlikler
- İşlemler

URL modeli:

```text
/overview
/image/recognize
/image/enroll
/videos/new
/videos/:jobId
/live
/live/connectors
/live/sessions/new
/live/sessions/:sessionId
/identities
/identities/:faceId
/processes
/processes/:processId
```

React Router v7 declarative/library mode kullanılacaktır. Mevcut Vite data katmanı korunur; framework mode veya SSR eklenmez. `NavLink` aktif navigasyonu, `useParams` ID route'larını ve route-level error boundary beklenmeyen render hatalarını yönetir.

## 8. Global Uygulama Kabuğu

`AppShell` aşağıdaki sabit bölgeleri sağlar:

- InterProbe marka alanı.
- Gruplanmış route navigasyonu.
- API health durumu.
- Aktif route başlığı ve kısa açıklaması.
- Global kopyalama feedback alanı.
- Route outlet.

Health kontrolü 30 saniyede bir yapılır; browser görünür değilken seyrekleşir. Health başarısız olduğunda son domain verisi silinmez, global stale/offline banner gösterilir.

## 9. Genel Bakış

Genel Bakış aşağıdakileri gösterir:

- API health.
- Live capabilities ve fixed-slot capacity.
- Aktif veya transition durumundaki live session'lar.
- Görüntü tanı, video yükle ve live session oluştur hızlı aksiyonları.
- Yalnızca current browser tarafından oluşturulan son process/job/session ID'leri.

Phase 2 global job-list endpoint'i olmadığı için sistemdeki bütün video job'larını gösteren sahte bir tablo oluşturulmaz. Browser recent list bir convenience alanıdır ve durable audit yerine geçmez.

## 10. Görüntü İş Akışları

### 10.1 Tanıma

- Tek image seçimi, drag/drop ve preview.
- Açık submit aksiyonu.
- Duplicate submit kilidi.
- Tüm yüzler için orijinal pixel bbox overlay.
- Overlay'den face seçimi ve karşılık gelen inspector vurgusu.
- `known`, `anonymous`, `new_anonymous` ayrımı.
- `faceId` ve `processId` için copy/deep-link.
- Sıfır yüz başarılı empty state olarak gösterilir.

### 10.2 Enrollment

- Tam olarak bir yüz zorunludur.
- Name ve metadata JSON alanları.
- İsteğe bağlı mevcut `faceId`, varsayılan formda değil “Gelişmiş” bölümünde yer alır.
- Otomatik embedding match ile anonymous-to-known promotion aynı `faceId` üzerinde açıklanır.
- `NO_FACE`, `MULTIPLE_FACES`, corrupt image ve inference hataları ayrıştırılır.

## 11. Video İş Akışı

### 11.1 Upload

- Tek video seçimi.
- Dosya adı ve boyut preview.
- Sampling mode: every frame, every N frame veya FPS.
- Mode'a göre yalnızca ilgili input görünür.
- Configured size/duration/container bilgisi helper copy olarak gösterilir.
- Submit sonucu `jobId`, `processId`, status ve deep-link kaydedilir.

### 11.2 Job İzleme

Job sayfası terminal duruma kadar otomatik polling yapar.

- Pending: queue durumu ve cancel.
- Processing: stage, progress, processed/total frames ve cancel.
- Cancelling: aksiyonlar kilitli, durable transition beklenir.
- Completed: result ve playback açılır.
- Failed: stable error code, process deep-link ve retry için yeni upload yönlendirmesi.
- Cancelled: audit korunur, result yoktur.

Polling kuralları:

- Aynı job için üst üste request yoktur.
- Başlangıçta kısa, uzun işlerde sınırlı backoff kullanılır.
- Terminal durumda durur.
- Page visibility hidden olduğunda seyrekleşir.
- Geçici hata son başarılı snapshot'ı silmez; stale işareti ekler.
- Route değişimi ve unmount abort/cleanup yapar.

### 11.3 Video Sonucu

`GET /videos/jobs/{jobId}/video` range destekli source olarak HTML `<video>` elementine bağlanır.

- `timeupdate`/frame sync ile aktif detection seti seçilir.
- Bbox'lar original video coordinate değerlerinden rendered media rect'e dönüştürülür.
- Person listesi `faceId`, status, name, confidence ve total duration gösterir.
- Appearance interval seçimi videoyu interval başlangıcına seek eder.
- Timeline, interval ve detection işaretlerini ayırır.
- Source retention dolduysa result metadata görünür kalır; player `VIDEO_EXPIRED` durumu gösterir.

## 12. Canlı İş Akışı

### 12.1 Session Listesi

- Fixed worker-slot kapasitesi.
- Session state ve desired state.
- Generation ve son runtime attempt.
- Son frame yaşı ve media readiness.
- Output modları: JSON, appearance, recording, annotated.
- Grid/detail görünüm geçişi.
- Delivery 4 öncesinde kapasite contract'ı ne döndürüyorsa UI onu aynen gösterir; dynamic concurrency varsaymaz.

### 12.2 Connector Yönetimi

- Webhook ve Kafka connector oluşturma.
- Secret alanları write-only.
- Response yalnızca safe connector snapshot gösterir.
- Connector ID session wizard içinde seçilebilir.
- Connector health/delivery problemi inference durumu gibi gösterilmez.

### 12.3 Session Oluşturma Sihirbazı

Dört adım kullanılır.

1. **Kaynak:** `rtspPull`, `whepPull` veya `whipPush`; source türüne özgü alanlar.
2. **İşleme:** sampling, detection/identity behavior ve güvenli varsayılanlar.
3. **Teslimatlar:** JSON connector/persistence, appearance, raw recording ve annotated output bağımsız seçimleri.
4. **Kontrol:** secret içermeyen özet, capacity uygunluğu ve submit.

Gelişmiş alanlar kapalı başlar. Alan görünürlüğü source/output seçimine göre belirlenir. Backend validation error'ları mümkünse ilgili adıma ve alana bağlanır.

`whipPush` oluşturulunca publisher'a verilmesi gereken public ingest URL bir kez güvenli response olarak gösterilir. Pull source URL hiçbir snapshot veya sonraki ekran tarafından tekrar gösterilmez.

### 12.4 Session Detayı

Ana düzen:

- Sol: annotated WHEP player veya output-disabled/failure state.
- Sağ: session/generation/run durumu ve kontrol aksiyonları.
- Alt: Frame Sonuçları, Görünümler, Kayıtlar, Çıktılar ve Olaylar sekmeleri.

Session detail aşağıdakileri sunar:

- Start/reconfigure/stop state feedback.
- Public annotated RTSP/WebRTC URL copy.
- Son persisted frame-result listesi.
- Bir frame seçildiğinde yüzler ve bbox/landmark detayları.
- Session appearance özeti ve identity deep-link.
- Recording segment listesi, detail ve retained content erişimi.
- Generation/run değiştiğinde eski ve yeni state'in karışmadığını açık label ile gösterme.

### 12.5 WHEP Playback

MediaMTX public URL biçimi `http(s)://host:8889/<opaque-path>/whep` olur. UI, MediaMTX WebRTC reader asset'ini kendi bundle'ından servis eder ve track'i `<video>` elementine bağlar.

- Reader mount'ta oluşturulur ve unmount/reconfigure'da `close()` edilir.
- `onTrack`, stream'i player'a bağlar.
- `onError`, playback-only error state üretir.
- Reconnect bounded ve görünür olur; sonsuz hızlı reconnect loop yoktur.
- Autoplay için video muted ve playsInline başlar.
- UI origin ayrıysa MediaMTX `webrtcAllowOrigins` listesine exact operator-console origin eklenir; deprecated `webrtcAllowOrigin` kullanılmaz.

Annotated output kapalıysa WHEP player oluşturulmaz. JSON-only session normal ve sağlıklı bir durumdur.

### 12.6 Multi-Camera Grid

Delivery 4 tamamlandıktan sonra:

- Her tile yalnızca kendi `sessionId` ve generation state'ini tüketir.
- Bir tile playback/reconnect hatası diğer tile'ları etkilemez.
- Grid capacity'den fazla session varsaymaz.
- Tile seçimi session detail route'una gider.
- Browser decode yükü için aynı anda autoplay yapan tile sayısı bounded tutulur; görünmeyen veya seçilmeyen tile poster/health moduna alınabilir.

## 13. Kimlik ve Process Kayıtları

### Kimlik

- Identity snapshot ve sample count.
- Known detail edit/deactivate.
- Görüntü history.
- Video appearance history: job, intervals ve source availability.
- Live appearance history: session, generation ve intervals.
- İlgili process/job/session route'larına deep-link.

### Process

- Process type, status, timestamps ve face count.
- Phase 1/2 compliance planında kalıcı hale getirilen task details.
- Immutable face snapshots.
- Sanitized event timeline.
- Video process ise job deep-link ve video counters.

UI missing optional event'i process failure gibi yorumlamaz; process record ve result tabloları authoritative'dir.

## 14. Ortak Bileşen Sınırları

```text
AppShell
DesktopGuard
RouteHeader
ServiceHealth
AsyncStateBoundary
ErrorNotice
CopyableId
StatusBadge
MediaViewport
  ImageMediaDriver
  VideoMediaDriver
  WhepMediaDriver
MediaOverlay
FaceInspector
IdentityLink
ProcessLink
Timeline
JsonDetails
ConfirmAction
```

Domain bileşenleri:

```text
image/
  RecognizePage
  EnrollPage
video/
  VideoUploadPage
  VideoJobPage
  VideoPlayer
  PersonTimeline
live/
  LiveOverviewPage
  LiveSessionWizard
  LiveSessionPage
  LiveSessionGrid
  ConnectorPage
  FrameResultPanel
  AppearancePanel
  RecordingPanel
records/
  IdentityPage
  ProcessPage
```

Bir domain başka domain'in internal state'ini import etmez. Geçişler URL ve stable IDs üzerinden yapılır.

## 15. API Katmanı

Mevcut tek `lib/api.ts` domain modüllerine ayrılır:

```text
src/api/client.ts
src/api/faces.ts
src/api/videos.ts
src/api/live.ts
src/api/processes.ts
src/api/types.ts
```

`client.ts` aşağıdakileri standartlaştırır:

- JSON/error envelope parsing.
- AbortSignal.
- Empty-body response.
- Range/media URL helper.
- Safe `ApiError` fields.
- Secret veya response body loglamama.

Frontend types backend camelCase contracts ile birebir eşleşir. UI backend'in snake_case internal isimlerini bilmez.

## 16. React Durum Modeli

- Ek global state kütüphanesi yoktur.
- URL shareable domain state'i taşır.
- Page-local data `useState`/`useReducer` ile yönetilir.
- Polling ve WHEP lifecycle custom hook'larda izole edilir.
- `useEffectEvent`, polling callback veya media event handler'ın güncel state/props okuması gerektiğinde bağlantıyı gereksiz yeniden kurmadan kullanılır.
- `startTransition`, ağır frame/person listesi filtreleri route veya playback kontrollerini bloklamasın diye kullanılır.
- `useDeferredValue`, uzun frame-result listesinde arama/filtre input'unu akıcı tutmak için kullanılır.
- Takımda React Compiler doğrulanmadan varsayılan olarak `useMemo`/`useCallback` eklenmez.

## 17. Async Durum ve Hata Davranışı

Her data surface şu durumları tanımlar:

- `idle`
- `loading`
- `empty`
- `success`
- `stale`
- `error`

Kurallar:

- Last-known-good data geçici fetch hatasında korunur.
- Form validation ile server error ayrıdır.
- Retry yalnızca idempotent GET veya açık kullanıcı aksiyonunda yapılır.
- Session create, reconfigure, stop, video cancel ve identity deactivate otomatik tekrar edilmez.
- Error panel varsa `code`, `processId`, `jobId`, `sessionId` ve generation bilgisini kopyalanabilir gösterir.
- Secret, URI, connector destination ve internal path hata detayında gösterilmez.

## 18. Erişilebilirlik

- Semantik heading sırası.
- Landmark bölgeleri ve anlamlı aria-label.
- Visible focus.
- Keyboard-operable overlay selection ve timeline.
- Dialog focus trap ve Escape davranışı.
- Status için renk + icon + text.
- Live update alanlarında kontrollü `aria-live`; frame başına announcement yoktur.
- Reduced-motion desteği.
- Minimum contrast WCAG AA hedefi.

## 19. Performans

- Frame-result listeleri bounded page/window ile render edilir.
- Video overlay yalnızca current timestamp çevresindeki detection'ları işler.
- Live grid aynı anda sınırsız WHEP reader açmaz.
- Polling request overlap yapmaz.
- Route-level lazy loading yalnızca bundle ölçümü gerek gösterirse eklenir; ilk plan gereksiz splitting yapmaz.
- Media playback failure hiçbir API polling loop'unu hızlandırmaz.

## 20. Test Stratejisi

### Unit/Component

- API adapter contract ve error parsing.
- Polling terminal/visibility/abort davranışı.
- Video timestamp-to-detection seçimi.
- Coordinate transform.
- Session wizard conditional fields ve secret clearing.
- WHEP mount/close/error/reconnect lifecycle.
- Status/empty/stale/error surfaces.

### Contract Fixtures

- Phase 1 recognition/enrollment/identity/process response'ları.
- Phase 2 submit/status/result/source/appearance response'ları.
- Dört live delivery'nin capabilities/session/frame/appearance/recording response'ları.
- Error envelope ve secret-redaction fixtures.

### Browser

Playwright desktop viewport ile:

- Image recognize ve bbox seçimi.
- Anonymous identity enrollment promotion.
- Video upload -> processing -> completed -> seek/overlay.
- Video cancel ve failed state.
- Live session wizard.
- Annotated WHEP success ve playback-only failure.
- Multi-camera tile isolation.
- Identity/process deep-link.
- `1279px` DesktopGuard.

### Gerçek Ortam Kabulü

- Real backend ve persistence ile non-destructive smoke.
- Real source video range playback.
- MediaMTX WHEP playback ve exact CORS origin.
- Birden fazla isolated live session.
- Recording content erişimi.
- Browser console'da secret/URI sızıntısı olmaması.

## 21. Uygulama Sırası ve Önkoşullar

UI implementasyonu backend contract'larından önce başlamaz. Sıra:

1. Phase 1/2 compliance planı uygulanır ve doğrulanır.
2. Live Delivery 1 session/control/capability contracts tamamlanır.
3. Live Delivery 2 frame/appearance contracts tamamlanır.
4. Live Delivery 3 recording/annotated public URLs tamamlanır.
5. Live Delivery 4 fixed-slot multi-camera tamamlanır.
6. Bu UI planı domain bazlı uygulanır.

UI task'ları backend delivery'lerle paralel tasarlanabilir ancak contract fixture dışında henüz var olmayan endpoint'e production call yazılmaz.

## 22. Başarı Kriterleri

- Tüm Phase 1, Phase 2 ve Phase 3 operatör akışları tek masaüstü konsoldan erişilebilir.
- Image, video ve live identity route'ları aynı persistent `faceId` etrafında birleşir.
- Video bbox playback ile doğru timestamp'te hizalanır.
- Annotated live output WHEP ile browser'da açılır ve reader temiz kapanır.
- JSON-only session, playback olmayan sağlıklı durum olarak görünür.
- Bir live tile arızası diğer session kontrollerini etkilemez.
- Secret değerler DOM, log, error veya API response render'ında yer almaz.
- Terminal job/session durumlarında polling durur.
- `1280x720` ve üzeri desteklenir; altı DesktopGuard gösterir.
- Türkçe metinler tutarlı, teknik ID/error code değerleri aynen korunur.
- TypeScript, frontend unit/component testleri, production build ve desktop Playwright akışları geçer.
