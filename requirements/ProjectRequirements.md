Face Recognition API
Proje Gereksinimleri

Giriş

Bu proje, görüntüler üzerinden yüz tanıma yapan, yalnızca API olarak çalışan bir servisin geliştirilmesini kapsar. Sistem, kendisine gönderilen bir görüntüdeki tüm yüzleri tespit eder, her yüzü sistemde tanımlı olan kimlikle (face ID) eşleştirir ve daha önce görülmüş yüzleri tutarlı biçimde aynı kimlikle döner. Sistemde kayıtlı yüzler ile daha önce görülmüş ancak isimlendirilmemiş anonim yüzler ayrı durumlarda raporlanır; böylece istemci, bir yüzün tanınıp tanınmadığını ve kim olduğunu net olarak ayırt edebilir.

Servis ayrıca güçlü bir izlenebilirlik katmanı sağlar: her API çağrısına benzersiz bir işlem kimliği (process ID) atanır, bu kimlik zaman damgası ve işlem detaylarıyla birlikte loglanır ve geriye dönük sorgulanabilir. Bu sayede belirli bir yüzün hangi işlemlerde ve ne zaman göründüğü takip edilebilir.

İlk etapta yalnızca tek görüntü üzerinden çalışacak şekilde tasarlanan sistem, ileride video ve canlı akış gibi yeni giriş tiplerine genişletilebilecek bir mimariyi hedeflemelidir.

1. Görüntü Girişi
    • API, her request içerisinde bir görüntü kabul edebilmeli.
    • Görüntünün geçerli/desteklenen bir formatta olduğu doğrulanmalı.
    • Görüntü okunamıyor, bozuk veya boş ise anlamlı bir hata dönülmeli.
    • Görüntüde hiç yüz bulunamadığı durum ayrı bir sonuç olarak ele alınmalı. Hata değil, "yüz bulunamadı" cevabı dönülmeli.

2. Face Detection
    • Görüntü içindeki tüm yüzler tespit edilmeli
    • Her tespit edilen yüz için görüntü üzerindeki konum bilgisi (bounding box vb.) dönülmeli.
    • Aynı görüntüde birden fazla yüz varsa hepsi bağımsız olarak işlenmeli.

3. Face Recognition
    • Tespit edilen her yüz için kalıcı bir kimlik (face ID) belirlenmeli; anonim yüzlerin de face ID'si olur.
    • Daha önce kayıtlı bir yüzle eşleşiyorsa, her zaman aynı face ID dönülmeli.
    • Eşleşme bir benzerlik/eşik mantığına göre yapılmalı; eşik altında kalan yüzler "tanınmadı" sayılmalı.
    • Her yüz için tanınma durumu (status) belirlenmeli ve dönülmeli:
        ◦ known: sistemde enroll edilmiş, isim/metadata'sı olan yüz.
        ◦ anonymous: daha önce görülmüş, mevcut ama isimlendirilmemiş anonim kayıt.
        ◦ new_anonymous: bu istekte ilk kez görülen, yeni oluşturulan anonim kayıt.
    • İsim ve ek metadata yalnızca known durumunda dolu olmalı; anonim durumlarda boş/null kalmalı.
    • Bir görüntüde hem bilinen hem anonim yüzler aynı anda bulunabilmeli ve her biri ayrı sonuçlanmalı.

4. Bilinmeyen Yüzlerin Saklanması
    • Mevcut kayıtlarla eşleşmeyen yüzler için otomatik olarak yeni bir anonim kimlik oluşturulmalı (new_anonymous).
    • Bu anonim kayıt veritabanına eklenmeli ve sonraki isteklerde aynı yüz tekrar gelirse aynı ID ile anonymous durumunda tanınmalı.
    • Anonim kayıtlar, kişisel bilgi (isim vb.) olmadan yalnızca tanıma için gerekli verilerle saklanmalı.
    • Anonim bir kimlik daha sonra enroll ile isimlendirilebilmeli; bu durumda aynı face ID korunarak status known'a geçmeli.

5. Veritabanı / Kayıt Yönetimi
    • Tanınan yüzlere ait kimlik verilerini(face ID) saklayacak kalıcı bir veri yapısı olmalı.
    • Yeni yüz ekleme / isimlendirme işlemi desteklenmeli (kayıt/enrollment).
    • Enroll edilen kayıtta isim ve ek metadata saklanabilmeli.
    • Mevcut bir kimliğin sorgulanması mümkün olmalı.
    • Bir kimliğin silinmesi/güncellenmesi desteklenmeli.
    • Aynı kişiye ait birden fazla yüz örneği saklanabilmeli (zamanla tanıma doğruluğunu artırmak için).

6. Recognition - İşlem Takibi
    • Her API çağrısı için sistem tarafından benzersiz bir process ID üretilmeli.
    • Bu process ID her zaman response içinde dönülmeli.
    • Process ID unique olmalı.
    • Bir process ID ile o işlemin sonradan tekrar sorgulanabilmesi mümkün olmalı.

7. Recognition - İşlem Loglama
    • Her process; process ID, zaman damgası (timestamp) ve task detayı ile birlikte loglanmalı.
    • Task detayı en az: işlem tipi, işlenen yüz sayısı, tespit edilen face ID'ler ve status bilgilerini içermeli.
    • Loglar kalıcı olarak saklanmalı ve sorgulanabilir olmalı.
    • Loglama, ana işlemin başarısını engellememeli (hata olsa bile işlem sonucu dönmeli).

8. Geçmiş / İlişki Sorgulama
    • Belirli bir face ID'nin daha önce hangi process'lerde ve ne zaman göründüğü sorgulanabilmeli.
    • Sonuç, ilgili process ID'leri ve zaman damgalarını içermeli.
    • Belirli bir process ID'ye ait detayların geri çağrılması mümkün olmalı.

9. API Davranışı
    • Sadece API olarak çalışmalı; herhangi bir kullanıcı arayüzü olmayacak.
    • Her endpoint için input/output contract’ı tanımlanmalı.
    • Cevaplar yapısal ve tutarlı bir formatta dönülmeli (örn. process ID + yüz listesi + her yüz için ID, status, isim, konum, skor).
    • Hata durumları standart ve ayırt edilebilir şekilde raporlanmalı.

10. Örnek API Endpoint'leri
    • POST /faces/recognize – Request ile gönderilen görüntü için tespit edilen yüzleri (face ID, status, isim, konum, skor) ve process ID'yi döner.
    • POST /faces/enroll – Bir yüzü/kişiyi isimle kaydeder; mevcut anonim ID'yi isimlendirebilir.
    • GET /faces/{faceId} – Bir face ID'nin detaylarını (status, isim, metadata) döner.
    • DELETE /faces/{faceId} – Bir face ID'yi siler.
    • GET /faces/{faceId}/history – Bir face ID'nin geçmiş process'lerini ve zamanlarını döner.
    • GET /processes/{processId} – Bir process'in detaylarını ve sonucunu döner.
11. Sonuç İçeriği
    • Her işlenmiş görüntü için: process ID, tespit edilen yüz sayısı.
    • Her yüz için:
        ◦ faceId – her zaman dolu (anonim de olsa).
        ◦ status – known / anonymous / new_anonymous.
        ◦ name – yalnızca known durumunda dolu, diğerlerinde null.
        ◦ metadata – kayıtlı kişiye ait ek bilgiler (varsa), anonimde boş.
        ◦ boundingBox – konum bilgisi.
        ◦ confidence – eşleşme güven skoru.

12. Deployment – Docker
    • API, Docker üzerinde çalışabilecek şekilde paketlenmeli
    • Projede bir Dockerfile bulunmalı ve image sorunsuz build edilebilmeli.
    • Container ayağa kalktığında API herhangi bir manuel ek adım olmadan çalışır durumda olmalı. 
    • Yapılandırma (port, eşik değeri, veri yolu vb.) ortam değişkenleri (environment variables) ile dışarıdan verilebilmeli. 
    • Kalıcı veriler container yeniden başlatıldığında kaybolmamalı
    • Birden fazla servis gerekiyorsa docker-compose ile tüm sistem ayağa kaldırılabilmeli.
