# ADR 0008: Doktrin her soruda aranır

- **Durum:** Kabul edildi
- **Tarih:** 2026-10-02

## Bağlam

Doktrin (ders notları ve öğreti), sohbet kutusundaki "Doktrin kaynakları" anahtarıyla
açılıyordu. Kaynak arama sayfasında da ayrı bir "Doktrin dahil" anahtarı vardı. Sohbetteki
anahtar varsayılan olarak kapalıydı; açılmadıkça cevaplar doktrinsiz yazılıyordu. Tercih
sohbet başına saklanıyordu (`conversations.doctrine_enabled`).

## Karar

Anahtarlar kaldırıldı. Doktrin her soruda, sohbetle aynı sorguyla aranır:

- **Sohbet ve web araması:** Doktrin araması kanun aramasından sonra yapılır. Kanun ve
  karar pasajları bütçenin hedef kısmını, doktrin kalanını doldurur; bu sıralama
  değişmedi.
- **Derin araştırma:** Soru için bir doktrin araması yapılır.
- **Kaynak arama sayfası:** Doktrin sonuçları her zaman ayrı bir listede gelir.
- **Dosya analizi:** Kanun gibi her hukuki konu için ayrı aranır, konu başına en fazla 8
  pasaj (kanunla aynı). Raporda her konunun altında, katkısı varsa bir "Öğretide:" maddesi
  yer alır. Analiz başta doktrinsiz kuruldu ve bir anahtarı yoktu; doktrin aynı gün
  ona da eklendi (`case-analysis-v2`).

Doktrin yardımcı bir kaynaktır. Doktrin indeksi yoksa ya da araması hata verirse cevap
doktrinsiz yazılır ve uyarı log'a düşer; soru bu yüzden başarısız olmaz.

API artık `include_doctrine` alanını kullanmaz. Eski bir istemci alanı gönderirse alan yok
sayılır. Veritabanındaki sütunlar kaldırılmadı:

- `chat_generations.include_doctrine` cevabın doktrinle mi yazıldığını kaydetmeye devam
  eder; artık her yeni cevapta `true` olur.
- `conversations.doctrine_enabled` artık kullanılmadığı için 2026-10-03'te kaldırıldı.

## Sonuç

Her cevap mevzuat, içtihat ve doktrine birlikte dayanır; kullanıcı bir seçim yapmak zorunda
kalmaz. Bedeli süredir: doktrin araması da 25 adayı reranker'dan geçirir. Sunucuda üç
soruda ölçülen doktrin araması 13–17 sn sürdü; kanun aramasıyla paralel çalıştırmak bir şey
kazandırmadı (sırayla 26–33 sn, birlikte 25–33 sn), çünkü ikisi de aynı 4 çekirdeği
kullanıyor. 25 doktrin pasajı modele ortalama 11 bin token daha gönderir; bu, Gemini'nin
dakikalık token sınırının çok altında kalır.

Dosya analizinde doktrin her konu için ayrı arandığından bedel konu sayısıyla artar. Örnek
dava dosyasında (5 konu) doktrin aramaları 87 sn, bütün analiz 231 sn sürdü. Raporda her
konunun altında bir "Öğretide:" maddesi çıktı; 7 doktrin atfının hepsi doğrulandı. Analizin
beklenen süresi 2–4 dakikadan 3–5 dakikaya çıktı.

Analizde konu başına kaç pasaj verileceği ölçülerek seçildi. Reranker sayıdan bağımsız olarak
25 adayı sıraladığı için sayı süreyi değil, modele giden metni değiştirir. Sunucuda
değerlendirme kümesinin 72 sorusunda (12 konudan 6'şar, beklenen maddesi belli olanlar)
kanun araması yapıldı; beklenen maddenin bulunduğu ilk sıra:

| İlk k sonuç | 4 | 6 | 8 | 10 | 12 | 16 | 20 | 25 |
|---|---|---|---|---|---|---|---|---|
| Beklenen madde içinde | %75 | %78 | %78 | %78 | %78 | %82 | %83 | %83 |

Bulunduğunda madde 60 sorunun 35'inde ilk sırada, 54'ünde ilk 4'teydi. 8'den 12'ye çıkmak
hiçbir soru kazandırmadı; 25'e çıkmak 4 soru kazandırıp modele konu başına üç kat metin
gönderirdi. 12 soruda (%17) madde ilk 25'te hiç yoktu: bu, sayıyla değil aday üretimiyle
(BM25 ve BGE-M3) ilgili bir eksiktir. Kanun ve doktrin bu yüzden konu başına 8'dir.
Doktrinin etiketli bir değerlendirmesi yok; 4 pasajla yapılan canlı denemede modele verilen
doktrin pasajlarının yarısına yakını rapora girmişti (21'den 10'u; kanunda 31'den 9'u).
