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
- **Dosya analizi:** Doktrin aranmaz. Analiz dava dosyası ve kanun üzerine kuruludur ve
  hiçbir zaman bir anahtara bağlı olmadı.

Doktrin yardımcı bir kaynaktır. Doktrin indeksi yoksa ya da araması hata verirse cevap
doktrinsiz yazılır ve uyarı log'a düşer; soru bu yüzden başarısız olmaz.

API artık `include_doctrine` alanını kullanmaz. Eski bir istemci alanı gönderirse alan yok
sayılır. Veritabanındaki sütunlar kaldırılmadı:

- `chat_generations.include_doctrine` cevabın doktrinle mi yazıldığını kaydetmeye devam
  eder. Sohbet ve araştırmada `true`, analizde `false` olur.
- `conversations.doctrine_enabled` artık yazılmaz.

## Sonuç

Her cevap mevzuat, içtihat ve doktrine birlikte dayanır; kullanıcı bir seçim yapmak zorunda
kalmaz. Bedeli süredir: doktrin araması da 25 adayı reranker'dan geçirir. Sunucuda üç
soruda ölçülen doktrin araması 13–17 sn sürdü; kanun aramasıyla paralel çalıştırmak bir şey
kazandırmadı (sırayla 26–33 sn, birlikte 25–33 sn), çünkü ikisi de aynı 4 çekirdeği
kullanıyor. 25 doktrin pasajı modele ortalama 11 bin token daha gönderir; bu, Gemini'nin
dakikalık token sınırının çok altında kalır.
