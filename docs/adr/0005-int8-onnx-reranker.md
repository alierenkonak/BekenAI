# ADR 0005: Reranker'ı int8 ONNX olarak çalıştırmak

- **Durum:** Kabul edildi
- **Tarih:** 2026-09-28

## Bağlam

Bir sohbet cevabı 2,5–3 dakika sürüyordu ve bunun büyük kısmı kaynak arama aşamasıydı.
Oracle A1 sunucusunda (4 OCPU, Neoverse-N1) ölçüm:

- Reranker'sız hibrit arama (BM25 + BGE-M3 + Qdrant): soru başına yaklaşık 0,5 sn.
- Reranker dahil (`bge-reranker-v2-m3`, 25 pasaj, PyTorch fp32): soru başına 43–57 sn.

Arama süresinin yaklaşık %98'i reranker'daydı. Doktrin kanalı ve dosya pasajları da
eklenince bir soruda reranker iki dakikayı buluyordu. Ücretsiz Oracle katmanı 4 OCPU ile
sınırlı; donanım büyütülemez.

## Karar

Reranker, sabitlenmiş Hub revizyonundan ONNX'e çevrilir. ONNX Runtime'ın CPU çekirdekleri
için attention, GELU ve LayerNorm katmanları birleştirilir ve ağırlıklar kanal bazında int8'e
dinamik olarak kuantize edilir (`python -m beken_retrieval export-reranker-onnx`). Model
servisi bu dosyayı `onnxruntime` ile çalıştırır. Bu paket zaten BGE-M3 için sabitlenmiş
bağımlılıklar arasındaydı. Dosya Hub'da değil model servisinin durum dizininde
(`/var/lib/bekenai-model-service/artifacts`) durur. Katalog yolunu ve SHA-256'sını sabitler,
servis de hash tutmazsa açılmaz. Model anahtarı ve revizyonu değişmediği için API ve worker
tarafında bir değişiklik gerekmez.

## Ölçüm

Sunucuda, 120 soruluk değerlendirme kümesinden konulara eşit dağılan 40 soru kullanıldı.
Her soruda canlı sistemin reranker'a verdiği 25 aday aynen alındı. Gemini veya başka bir
dış API kullanılmadı.

| Sürüm | Ortalama | Medyan | p95 | İlk sonuç aynı | İlk 10 örtüşme | Spearman | Beklenen madde ilk 10'da |
|---|---|---|---|---|---|---|---|
| PyTorch fp32 (önceki) | 50,6 sn | 46,6 sn | 89,8 sn* | — | — | — | 25/29 |
| ONNX fp32, birleştirilmiş | 41,9 sn | 41,6 sn | 51,2 sn | %100 | %100 | 1,000 | 25/29 |
| **ONNX int8** | **14,4 sn** | **14,2 sn** | **18,1 sn** | %93 | %97 | 0,988 | **25/29** |

\* PyTorch turu sırasında canlıda bir sohbet sorusu işlendi; p95 bundan etkilenmiş olabilir.
Medyan, canlıda ayrıca ölçülen 43–57 sn ile tutarlıdır.

Karşılaştırma için: reranker'sız sıralama beklenen maddeyi 29 sorudan 23'ünde ilk 10'a
getiriyor. Yerel PyTorch referansı, canlı reranker'la 5 soruda aynı ilk 10'u verdi. Repodaki
dışa aktarma komutu, ölçülen dosyanın bayt bayt aynısını (aynı SHA-256) üretti.

## Sonuç

- Reranker yaklaşık 3,3 kat hızlanır ve süresi daha kararlı olur. Model dosyası 2,27 GB'tan
  570 MB'a iner ve servis 38 sn yerine yaklaşık 9 sn'de açılır. PyTorch reranker modeli artık
  belleğe yüklenmez; `torch` kütüphanesi ise tokenizer için `transformers` üzerinden yine
  import edilir.
- Canlıya alındıktan sonra aynı yöntemle beş soruda ölçülen reranker'lı arama 10,6–20,8 sn
  (ortalama yaklaşık 15 sn) sürdü; önceki PyTorch sürümünde 42,7–57,4 sn (ortalama yaklaşık
  47 sn) sürüyordu.
- Sıralama int8 yuvarlaması yüzünden 40 sorunun 3'ünde ilk sırada değişir. İlk 10'un %97'si
  aynı kalır; beklenen madde ölçütünde kayıp yoktur.
- Sohbet, reranker'ın sıraladığı 25 adayın hepsini modele verir. Bu yüzden int8 farkı
  sohbette yalnız pasajların sırasını etkiler, hangi pasajın gönderildiğini değiştirmez.
  Arama sayfası ilk 10'u gösterir.
- fp32 ONNX yalnız 1,2 kat kazandırdığı için seçilmedi.
- Geri alma: önceki sürüme dönülür (katalogda `backend: torch`) ve model servisi yeniden
  başlatılır; PyTorch yolu kodda duruyor.
