# ADR 0011: Planlayıcının madde ipuçları

- **Durum:** Kabul edildi
- **Tarih:** 2026-10-06

## Bağlam

Türkçe kök bulmadan sonra (ADR 0010), değerlendirme kümesinin 72 sorusundan 4'ünde beklenen
kanun maddesi aramanın ilk 25 sonucunda hâlâ yoktu. Sunucuda incelenen dört maddenin
dördü de reranker'ın önüne konduğunda ilk 25'e giriyordu (17., 22., 17. ve 20. sıralar).
Yani sorun sıralama değil, maddenin aday listesine girememesiydi:

| Soru | Beklenen madde | Kelime araması | Anlam araması |
|---|---|---|---|
| İstifa ve kıdem | 1475 m.14, 4857 m.24 | 24. | 15. |
| Muvazaa | 4857 m.2 | 31. | 25. |
| Fazla çalışma zamanaşımı | 4857 Ek 3 | 114. | 51. |
| Hizmet tespiti | 5510 m.86 | 132. | ilk 200'de yok |

Bu maddeler uzun ve birden çok konuyu düzenleyen pasajlar (2.000–3.000 karakter). Soru
bunların içindeki tek bir fıkrayla ilgili. Reranker yalnız ilk 512 token'ı, yani yaklaşık
1.700 karakteri okuyor. Kanun pasajlarının %22'si, karar pasajlarının %30'u bu sınırı
aşıyor.

## Ölçüm

Aynı 72 soru, sohbetteki yolla ölçüldü: planlayıcı (3.5 Flash Lite), hibrit arama ve
reranker. Dört seçenek karşılaştırıldı:

- **Madde ipucu:** planlayıcı, soruyu düzenleyen en fazla 3 kanun maddesini de yazar. Bu
  maddeler numarasıyla getirilip reranker'ın aday listesine eklenir.
- **Pencereli puanlama:** 1.700 karakteri aşan pasajlar örtüşen pencerelere bölünür. Her
  pencere ayrı puanlanır ve en yüksek puan pasajın puanı sayılır.
- İkisi birlikte.
- Hiçbiri (önceki durum).

| | İlk 3 | İlk 8 | İlk 25 |
|---|---|---|---|
| Önceki | %69 | %85 | %94 |
| **Madde ipucu** | **%71** | **%86** | **%97** |
| Pencereli puanlama | %72 | %85 | %94 |
| İkisi birlikte | %74 | %86 | %97 |

Madde ipucu:

- Planlayıcı 72 sorunun 65'inde toplam 76 madde önerdi. 55 soruda önerdiği maddelerden
  biri beklenen maddeydi.
- 4 soru iyileşti; hiçbiri kötüleşmedi.
- İstifa ve muvazaa soruları ilk 25'e girdi. "Kıdem tazminatına hak kazanma" sorusunda
  1475 m.14, 15. sıradan 1. sıraya çıktı.
- Soru başına ortalama 1,4 pasaj daha reranker'dan geçiyor; bu yaklaşık 1 sn.

Pencereli puanlama:

- 7 soruyu iyileştirdi, 6 soruyu kötüleştirdi; değişiklikler çoğunlukla bir sıra.
- İlk 8 ve ilk 25 değişmedi.
- Reranker'ın puanladığı metin soru başına 26'dan 44 pasaja çıkıyor, bu da aramaya yaklaşık
  10 sn ekliyor.

## Karar

- `QueryPlan.articles`: planlayıcı, soruyu doğrudan düzenleyen en fazla 3 kanun maddesini
  yazar. Emin olmadığı maddeyi yazmaz, yönetmelik ve karar yazmaz.
- Kod, maddeyi indeksteki etikete çevirir ("Ek madde 3" → `Ek3`, "geçici 20. madde" →
  `Geçici20`, "m. 18/a" → `18/A`).
  - Kanun numarası ya da madde okunamazsa ipucu atılır.
  - Şema bilerek gevşektir; garip bir ipucu planın tamamını düşürmemeli.
- Sohbetin kanun aramasında her ipucu maddenin ilk 3 pasajı aday listesine eklenir ve
  reranker diğer adaylarla birlikte sıralar. Yanlış madde önerilirse reranker onu aşağıya
  atar. Doktrin aramasına ipucu verilmez.
- Pencereli puanlama uygulanmadı.

## Sonuç

- İlk 25'te beklenen maddeyi bulma %94'ten %97'ye çıktı.
- Hâlâ bulunamayan iki soru var:
  - **Fazla çalışma zamanaşımının başlangıcı.** Planlayıcı yakın ama yanlış maddeler önerdi
    (4857 m.32, TBK m.146). İlk sırada TBK m.149 ("zamanaşımı alacağın muaccel olmasıyla
    başlar") geliyor; soruyu cevaplayan madde de odur. Değerlendirme etiketi TBK'yı madde
    numarası olmadan verdiği için bu ölçümde bulunmuş sayılmadı. Etiket aynı gün düzeltildi
    (aşağıya bakın).
  - **Hizmet tespiti.** Planlayıcı 5510 m.86'yı bilmedi.
- İpuçları şimdilik yalnız sohbette kullanılıyor. Dosya analizi ve derin araştırma kendi
  sorgularını yazıyor; onlar ölçülmeden değiştirilmedi.

## Tekrarlanabilir ölçüm (2026-10-06)

Bu ölçüm artık repodaki bir komutla tekrarlanabiliyor (sunucuda, API'nin ortamıyla):

```
python -m app.chat.retrieval_eval --queries evals/labour_law/queries.v1.jsonl --out report/
```

- Komut, beklenen kanun maddesi belli olan soruları seçer. Varsayılan konu başına 6 sorudur;
  bu, bu ADR'deki 72 sorudur. `--per-topic 0` hepsini alır.
- Her soru sohbetin planlayıcısından geçer ve plan `report/plans.jsonl`'a kaydedilir.
  Sonraki çalıştırmalar model çağırmaz, yalnız aramayı ölçer. Dosya silinirse sorular
  yeniden planlanır. Planlayıcı hata verirse soru kendi kelimeleriyle aranır, plan
  kaydedilmez ve raporda işaretlenir.
- Arama sohbetin kanun aramasıyla aynıdır, madde ipuçları dahil. `--no-hints` ipuçsuz
  ölçer.
- `report.json`, her soru için beklenen maddenin sırasını, planlanan sorguyu, ipuçlarını ve
  ilk sonucu içerir.

L084'ün ("Fazla çalışma alacağında zamanaşımı ne zaman başlar?") beklenen kaynağı `6098`
yerine `6098:149` olarak düzeltildi.

Komut sunucuda bu ADR'deki deneyin planlarıyla, yani aynı sorgu ve ipuçlarıyla çalıştırıldı:

| | İlk 1 | İlk 3 | İlk 8 | İlk 25 |
|---|---|---|---|---|
| Madde ipucu yok | %50 | %74 | %88 | %96 |
| **Madde ipucu** | **%51** | **%75** | **%89** | **%99** |

- İpucu 5 soruyu iyileştirdi, hiçbirini kötüleştirmedi.
- İlk 25'te bulunamayan tek soru hizmet tespitinde hak düşürücü süre (5510 m.86).
  Planlayıcı bu soruda madde önermedi. Öteki hizmet tespiti sorusunda m.86'yı önerdi ve
  madde 17. sırada geldi.
- Arama başına ortalama 15,6 sn sürdü (yalnız kanun araması).
- Planlayıcı sıfırdan çalıştırıldığında (konu başına 1, toplam 12 soru) 12 sorunun
  hepsinde beklenen madde ilk 25'teydi; planlayıcı hata vermedi.

Deneydeki sayılardan farkın bir sorusu L084'ün etiketidir. Kalan fark, 15 soruda 1–4
sıralık kaymalardır ve iki yönde de olur. Sebebi reranker'dır:

- Reranker pasajları uzunluğa göre sıralayıp 8'li gruplar halinde puanlıyor. int8 modelde
  bir pasajın puanı, aynı grupta puanlandığı pasajlara göre değişiyor.
- Sunucuda 10 pasaj tek başına ve 20 başka pasajla birlikte puanlandı. Puanlar 0,10'a kadar
  (ortalama 0,035) değişti ve yakın puanlı iki pasajın sırası yer değiştirdi. Aynı istek
  tekrarlandığında puanlar birebir aynı.
- Deney pencere metinlerini de aynı isteğe koyduğu için gruplar farklıydı.

Bu yüzden aday listesine bir pasaj eklemek, başka pasajların sırasını da bir iki basamak
oynatabilir. Seçenekleri karşılaştırırken her seçenek aynı komutla çalıştırılmalı. Planlayıcı
da çalıştırmadan çalıştırmaya farklı sorgu yazabildiği için aynı `plans.jsonl` kullanılmalı.
