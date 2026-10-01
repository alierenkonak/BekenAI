# ADR 0007: Derin araştırma

- **Durum:** Kabul edildi
- **Tarih:** 2026-10-02

## Bağlam

Sohbet, soruyu tek bir sorguyla arar ve yaklaşık 25 pasajdan bir cevap yazar. Birden fazla
şartı, istisnası ve usulü olan sorularda (örneğin "performans düşüklüğüyle fesihte savunma ve
ispat yükü") bu tek arama her parçayı yeterince bulamıyor. Bir de, bulunan kararların
dayandığı maddeler çoğu zaman sonuçlarda yer almıyor.

Gemini API'nin hazır derin araştırma ajanı ve Google Search bağlantısı değerlendirildi:

- Açık web'i arıyorlar; mevzuat, içtihat, doktrin ve kullanıcının dava dosyasından oluşan
  kaynaklarımızı görmüyorlar.
- Çıktıları cümle doğrulamasından, atıf bütünlüğünden ve yürürlük kontrollerinden geçemiyor.
- Google Search, Gemini 3.x için ücretsiz katmanda yok (ADR 0004).

## Karar

Derin araştırma kendi kaynaklarımız üzerinde, sınırlı adımlı bir döngüdür
(`app/chat/research.py`):

1. **Plan:** Gemini 3.7 Flash, soruyu en fazla 5 alt soruya böler; her biri için bir arama
   sorgusu yazar.
2. **Birinci tur:** Her alt soru için hibrit arama ve reranker çalışır. Sohbette dosya varsa
   dosyada da aranır. Doktrin anahtarı açıksa bir doktrin araması eklenir.
3. **Eksik analizi:** 3.7 Flash, her alt sorunun bulduklarının kısa özetine bakar. Eksik kalan
   kanun hükmü, karar, istisna ya da süre için en fazla 4 ek sorgu yazar.
4. **Atıf takibi:** Model kullanılmaz. Bulunan kararların ve doktrinin dayandığı maddeler
   metinden okunur (ADR 0006). Bulunmamış olanların en çok atıf alan 4'ü, kanun ve madde
   numarasıyla doğrudan getirilir (`DomainSearchCoordinator.article_hits`). Bu bir arama değil,
   bellekteki kayıtlardan yapılan kesin bir eşleşmedir.
5. **İkinci tur ve rapor:** Ek sorgular aranır. Kanun pasajlarına yürürlük notları eklenir.
   3.7 Flash başlıklı raporu yazar:
   - kısa cevap,
   - her alt soru için kanun, içtihat, doktrin ve dosyadaki karşılığı,
   - uygulamada dikkat edilecekler,
   - açık kalan noktalar.

   Rapor, sohbetle aynı cümle doğrulamasından geçer (3.5 Flash Lite).

Diğer kurallar:

- **Maliyet sabittir:** 3.7 Flash ile 3 çağrı ve 3.5 Flash Lite ile 1 çağrı; yaklaşık 8–10
  arama. Kaynaklar 90 bin token'lık bir bütçeye sığdırılır.
  - Kırpma, her alt sorunun en iyi pasajları sırayla alınarak yapılır; hiçbir alt soru boş
    kalmaz.
  - Atıf takibi ve web araması başarısız olursa rapor onlarsız yazılır.
- **Web:** Derin araştırma yalnız "Web araması" anahtarı da açıksa web'i arar. Plan genel bir
  web sorgusu yazar ve sonuç, sohbetteki gibi raporun altında etiketli bir bölüme gider.
- **Bayrak:** Derin araştırma, `chat_generations.deep_research` bayrağıdır, ayrı bir
  `search_mode` değildir; bu yüzden web aramasıyla birlikte açılabilir. Dosya analiziyle
  birlikte açılamaz; analiz zaten bir rapordur.
- **Arayüz:** Sohbet kutusunda "Derin araştırma" anahtarı vardır. Sadece bir soru için
  geçerlidir; soru gönderilince kapanır ve takip soruları normal cevapla devam eder.
  - İlerleme adımları araştırmaya özeldir.
  - Raporun altında hangi alt soruların arandığını, kaç arama yapılıp kaç pasaj okunduğunu ve
    hangi maddelerin atıftan getirildiğini gösteren bir "Araştırma özeti" vardır.

## Sonuç

Çok parçalı sorular parça parça ve iki turda aranır; kararların dayandığı maddeler cevaba
girer. Bedeli süredir: araştırma 3–5 dakika sürer, sohbet ise yaklaşık 1 dakika. Model ve
arama sayısı sınırlı olduğu için kota tüketimi öngörülebilir kalır. 3.7 Flash'ın kendi
kotası, sohbetin 3.8 Flash'ını ve analizin 3.6 Flash'ını etkilemez.
