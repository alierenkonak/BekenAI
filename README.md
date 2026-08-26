# Beken.ai

Beken.ai, Türk İş Hukukuna odaklanan, yalnız doğrulanabilir hukuk kaynaklarına dayanarak yanıt üretmeyi hedefleyen bir legal intelligence projesidir.

Bu repo şu anda **Aşama 0 — Proje Temeli** durumundadır. Arama, RAG, veri toplama, citation üretimi ve özel dosya analizi henüz uygulanmamıştır.

## İlk MVP hedefi

İlk MVP bireysel iş hukukunda fesih, işe iade, işçilik alacakları, yıllık izin, eşit davranma, iş sözleşmesinin niteliği, alt işverenlik, işyeri devri, arabuluculuk, zamanaşımı ve ispat konularını kapsayacaktır.

Temel ürün ilkesi:

> Yeterli doğrulanmış kaynak varsa kaynaklı yanıt ver; yoksa kaynak yetersizliğini açıkça bildir.

## Monorepo yapısı

```text
BekenAI/
├── frontend/       Next.js tabanlı kullanıcı arayüzü
├── backend/        FastAPI uygulaması
├── ingestion/      Aşama 1 veri alma ve ayrıştırma paketi
├── evals/          Retrieval ve citation değerlendirmeleri
├── tests/          Uçtan uca testler
├── docs/adr/       Mimari karar kayıtları
├── scripts/        Geliştirme yardımcıları
└── docker-compose.yml
```

## Gereksinimler

- Node.js 22 LTS
- Python 3.12 veya 3.13
- Docker Desktop ve Docker Compose
- GNU Make veya eşdeğer komutların elle çalıştırılması

## Yerel kurulum

```bash
cp .env.example .env
make setup
make infra-up
```

Servisleri ayrı terminallerde başlatın:

```bash
make backend-dev
make frontend-dev
```

- Frontend: `http://localhost:3000`
- API: `http://localhost:8000`
- OpenAPI: `http://localhost:8000/docs`
- Qdrant: `http://localhost:6333/dashboard`

## Sağlık kontrolleri

- `GET /health/live`: API sürecinin çalıştığını doğrular.
- `GET /health/ready`: PostgreSQL ve Qdrant bağlantılarını kontrol eder; başlangıç corpus belge sayısı `0` değerindedir.

## Doğrulama

```bash
make validate
```

Bu komut frontend lint/build, backend lint/test ve Docker Compose yapılandırma kontrollerini çalıştırır.

## Veri ve citation ilkeleri

- Raw hukuk belgeleri değiştirilmeyecek ve kaynağıyla birlikte izlenecektir.
- Global hukuk corpus'u ile kullanıcıya ait özel dosyalar farklı namespace ve erişim sınırlarında tutulacaktır.
- LLM'e karar veya citation kimliği uydurtulmayacaktır.
- Citation kimliği gerçek belge ve exact passage ile deterministik olarak eşlenecektir.
- Yeterli kanıt bulunmayan sorularda sistem cevap üretmeyi reddedebilecektir.

## Aşama 1'e geçiş şartları

- Frontend production build'i başarılı olmalı.
- Backend testleri ve health endpoint'leri geçmeli.
- PostgreSQL ve Qdrant healthcheck'leri başarılı olmalı.
- CI doğrulamaları temiz çalışmalı.
- Corpus, upload, model, index ve credential dosyaları Git'e girmemeli.

## Lisans

Bu repository şu anda bir açık kaynak lisansı altında yayımlanmamaktadır. Tüm hakları saklıdır.

