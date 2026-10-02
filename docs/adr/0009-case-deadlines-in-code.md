# ADR 0009: Dosya analizindeki süreler kodla hesaplanır

- **Durum:** Kabul edildi
- **Tarih:** 2026-10-02

## Bağlam

Dosya analizi raporunun "Kritik süreler" bölümünü model yazıyordu: sürenin başladığı tarihi
dosyadan, süreyi kanundan alıyor, son günü kendisi hesaplıyor ve işlemin süresinde yapılıp
yapılmadığına kendisi karar veriyordu.

Örnek dava dosyasında yedek model (3.5 Flash Lite) şu cümleyi yazdı: 05.07.2023'teki
arabuluculuk başvurusuyla, son günü yaklaşık 14.07.2023 olan bir aylık sürenin "aşıldığı
anlaşılmaktadır". Doğrusu, başvuru süresi içindeydi. Raporun aynı konudaki "Değerlendirme"
maddesi doğruydu; iki cümle birbiriyle çelişiyordu. Cümle doğrulaması bu cümleyi yalnız
"kısmen destekleniyor" diye işaretledi; bir tarih karşılaştırmasının doğru olup olmadığını
kaynaklardan anlayamaz.

## Karar

Model süre hesabı yapmaz; yalnız olguları verir (`app/chat/deadlines.py`).

1. **Olgular:** Dosyanın tamamını okuyan ilk çağrı, yasal bir süreye bağlı her konu için
   yalnız şunları yazar:
   - süreyi (örneğin 1 ve "ay");
   - sürenin başladığı olayı ve tarihini;
   - yapıldıysa, süre içinde yapılması gereken işlemi ve tarihini.
2. **Kontrol:**
   - Tarihler dosyada aynen geçmelidir (ADR 0006'daki tarih kontrolüyle aynı).
   - Süre, o konu için bulunan kanun pasajlarında rakamla ya da yazıyla geçmelidir ("1 ay",
     "bir aylık", "on beş gün").
   - Biri tutmazsa o konu için hesap yapılmaz.
3. **Hesap:** Son gün HMK m.92'ye göre hesaplanır:
   - Başlangıç günü sayılmaz.
   - Ay ve yıl olarak belirlenen süre karşılık gelen günde, o gün yoksa ayın son gününde
     biter.
   - İş günü olarak belirlenen sürede cumartesi ve pazar atlanır.
   - Resmî tatiller bilinmez. Son gün hafta sonuna denk gelirse sürenin uzayabileceği
     söylenir. Her son gün "yaklaşık" diye verilir.
4. **Rapor:** Hesap sonucu rapor modeline konu listesinde verilir; model "Değerlendirme"de
   son günü ve sonucu oradan aynen alır. Hesaplanmamış bir süre için son gün yazmaz ve
   sürenin geçip geçmediğine hüküm kurmaz.
   - "Kritik süreler" bölümünü kod yazar.
   - Model bölümü yine de yazarsa, o bölüm kaldırılır.
   - Bölümün cümleleri süreyi veren kanun pasajına ve tarihleri veren dosya pasajlarına atıf
     yapar ve diğer cümleler gibi doğrulanır.

## Sonuç

Son gün ve "süre içinde / süre dolduktan sonra" sonucu artık modelden bağımsızdır. Ek
Gemini çağrısı yoktur; olgular zaten dosyayı okuyan çağrıda istenir. Bedeli kapsamdır:
dosyada tarihi yazmayan ya da kanun pasajında geçmeyen bir süre "Kritik süreler"e girmez ve
model onun için son gün yazmaz. Resmî tatiller hesaba katılmaz; rapor bunu açıkça söyler.
