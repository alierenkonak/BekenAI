# ADR 0002: Global ve private veri sınırı

- **Durum:** Kabul edildi
- **Tarih:** 2026-08-26

## Bağlam

Platform hem ortak Türk hukuku corpus'unu hem kullanıcıların özel dosyalarını işleyecektir. Özel içeriğin global indekslere karışması kabul edilemez.

## Karar

Global belgeler ve özel dosyalar ayrı storage namespace ve vector collection sınırlarında tutulacaktır. Her private kayıt `workspace_id` taşıyacak; API ve repository katmanlarında workspace filtresi zorunlu olacaktır.

## Sonuç

Combined RAG iki ayrı retrieval sonucunu kontrollü biçimde birleştirecek; ingestion hiçbir özel chunk'ı global corpus'a yazamayacaktır.

