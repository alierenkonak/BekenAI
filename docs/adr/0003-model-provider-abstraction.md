# ADR 0003: Model-provider bağımsızlığı

- **Durum:** Kabul edildi
- **Tarih:** 2026-08-26

## Bağlam

Ücretsiz hosted model seçenekleri, maliyetler ve kalite zamanla değişebilir. Ürünün hukuki değeri tek bir modele bağlanmamalıdır.

## Karar

LLM kullanımı ileride `generate`, `stream` ve `structured_output` yeteneklerini sunan provider arayüzünün arkasında tutulacaktır. Provider seçimi environment configuration ile yapılacaktır.

## Sonuç

Groq, OpenRouter veya gelecekteki self-hosted modeller retrieval ve citation çekirdeği değiştirilmeden değiştirilebilir.

