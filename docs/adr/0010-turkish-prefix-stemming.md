# ADR 0010: Kelime aramasında Türkçe kök bulma (ilk 5 harf)

- **Durum:** Kabul edildi
- **Tarih:** 2026-10-02

## Bağlam

Kelime araması (BM25) kelimeleri olduğu gibi karşılaştırıyordu. Türkçe ekler yüzünden
"savunmam alınmadan" ile İş Kanunu m.19'daki "savunmasını almadan" aynı kelime sayılmıyordu.
Bu soruda m.19, kelime aramasının ilk 100 sonucunda bile yoktu.

Değerlendirme kümesinin 72 sorusunda (12 konudan 6'şar, beklenen maddesi belli olanlar)
sohbetteki yolun tamamı ölçüldü. Her soru önce sohbetin planlayıcısından (3.5 Flash Lite)
geçti, sonra hibrit arama ve reranker çalıştı. Planlayıcı sorguları bir kez üretilip
saklandı; denemeler model çağırmadı.

Reranker her pasajı diğerlerinden bağımsız puanlar. Bu yüzden her soruda bütün seçeneklerin
adayları bir kez puanlandı, her seçeneğin sonucu bu puanlardan hesaplandı.

## Ölçüm

Kelime araması tek başına, beklenen madde ilk 25'te:

| Kök bulma | Yok | İlk 4 harf | İlk 5 harf | İlk 6 harf | İlk 7 harf |
|---|---|---|---|---|---|
| Bulunan soru | 56 | 64 | **66** | 63 | 63 |

Arama yolunun tamamı (BM25 + BGE-M3 + RRF + reranker):

| | İlk 8 | İlk 25 |
|---|---|---|
| Kök bulma yok, reranker'a 25 aday (önceki) | %83 | %92 |
| Kök bulma yok, 30–50 aday | %83 | %92 |
| **İlk 5 harf, 25 aday** | **%85** | **%94** |
| İlk 5 harf, 30 aday | %85 | %96 |
| İlk 5 harf, 35–50 aday | %86 | %96 |

Ham soruyla (planlayıcısız) yapılan önceki ölçüm %81 ve %86'ydı. Planlayıcı tek başına
ilk 25'i %86'dan %92'ye çıkarıyor.

## Karar

- Kelime araması, harfle başlayan kelimeleri ilk 5 harfine indirerek indekslenir ve aranır
  (`tokenization.prefix_stem`). "savunmasını" ve "savunmam" ikisi de "savun" olur. Kesme
  işaretinden sonraki ek atılır ("kanun'un" → "kanun"). Sayılar ve karar numaraları
  ("e.2022/123", "18/a") olduğu gibi kalır.
- Yöntem profilde kanal bazında tutulur (`lexical_stemming: {"primary": "prefix5"}`).
  Her indeks hangi yöntemle kurulduğunu kendi manifestine yazar ve sorguyu aynı yöntemle
  işler. Bu yüzden eski bir indeks, değişmeden çalışmaya devam eder.
- Reranker'a giden aday sayısı 25'te kalır. 35 aday, kök bulmayla 72 sorudan yalnız 1'ini
  daha ilk 25'e sokuyor. Buna karşılık ölçülen reranker süresi aday başına yaklaşık 0,58
  sn; 10 aday her aramaya yaklaşık 6 sn ekler. Bu, sohbette cevap başına iki, dosya
  analizinde konu başına iki arama demek.
- İlk 5 harf, kelime aramasında 4, 6 ve 7 harften iyi çıktı. Türkçe bilgi erişimi
  çalışmalarında da sabit önek kök bulmanın iyi sonuç verdiği bilinir. Yeni bir paket
  gerektirmez.

## Sonuç

- Kök bulmayla 8 soru iyileşti; 3'ünde madde ilk 25'e yeni girdi: işe başlatma başvurusu,
  eşit davranmama tazminatı, sigortasız çalışmanın tespiti.
- 5 soru geriledi; 4'ünde yalnız bir iki sıra. "İstifa eden işçi hangi durumlarda kıdem
  tazminatı alabilir?" sorusunda madde 15. sıradan 25'in dışına çıktı.
- Yöntem ilk 25'te bulmayı %92'den %94'e, ilk 8'de bulmayı %83'ten %85'e çıkarır.
- İlk 25'te hâlâ bulunamayan 4 soru:
  - istifa ve kıdem (1475 m.14, 4857 m.24);
  - muvazaalı alt işverenlik (4857 m.2);
  - fazla çalışma alacağında zamanaşımı;
  - hizmet tespiti davasında hak düşürücü süre (5510 m.86).
- Doktrin indeksinde kök bulma kullanılmıyor (aşağıdaki doktrin ölçümüne bakın).

## Doktrin ölçümü (2026-10-06)

Doktrinin etiketli sorusu olmadığı için bilinen pasajı bulma yöntemiyle ölçüldü:

- Doktrinden rastgele 40 pasaj seçildi (en az 500 karakter).
- Her biri için Gemini Flash Lite, bir kullanıcının soracağı gibi bir soru yazdı. Pasajın
  ifadelerini kopyalamaması, madde numarası yazmaması istendi.
- Soru sohbetteki gibi planlayıcıdan geçti.
- Aramanın, sorunun üretildiği pasajı kaçıncı sırada bulduğuna bakıldı.

| | İlk 1 | İlk 3 | İlk 8 | İlk 25 |
|---|---|---|---|---|
| Arama yolunun tamamı, kök bulma yok | %72 | %90 | %98 | %100 |
| Arama yolunun tamamı, ilk 5 harf | %72 | %90 | %98 | %100 |
| Yalnız kelime araması, kök bulma yok | %57 | %78 | %90 | %100 |
| Yalnız kelime araması, ilk 5 harf | %45 | %85 | %88 | %98 |

- Kök bulma arama yolunun tamamında hiçbir soruyu iyileştirmedi; 2 soruda sıra biraz
  geriledi (4. → 5. ve 11. → 13.).
- Anlam araması doktrinde tek başına ilk 8'de %95'e ulaşıyor. Doktrin, kanun maddelerinden
  farklı olarak açıklayıcı düzyazı; kelime eşleşmesine daha az dayanıyor.
- Kök bulma bu yüzden kanal bazında ayarlanır (`lexical_stemming: {"primary": "prefix5"}`):
  kanun kanalı kök bulur, doktrin bulmaz. Doktrin indeksi ileride yeniden kurulursa da
  kök bulmasız kurulur.
- Sentetik sorular pasajdan üretildiği için kelime aramasının lehine olabilir. Yine de kök
  bulma kelime aramasının en üst sırasını bile kötüleştirdi.
