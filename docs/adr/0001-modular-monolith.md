# ADR 0001: Modüler monolith

- **Durum:** Kabul edildi
- **Tarih:** 2026-08-26

## Bağlam

Beken.ai tek geliştirici ve sıfıra yakın bütçeyle başlayacaktır. Retrieval, citation, ingestion ve özel dosya iş akışlarının sınırları açık olmalı; erken mikroservis operasyonu taşınmamalıdır.

## Karar

Next.js frontend ve FastAPI backend içeren bir monorepo kullanılacaktır. Backend ilerleyen aşamalarda domain modüllerine ayrılacak ancak tek deploy edilebilir uygulama olarak kalacaktır.

## Sonuç

Modüller açık sözleşmelerle ayrılır. Bağımsız ölçekleme ihtiyacı ölçülmeden mikroservis oluşturulmaz.

