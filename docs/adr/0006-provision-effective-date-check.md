# ADR 0006: Yürürlük kontrolü

- **Durum:** Kabul edildi
- **Tarih:** 2026-09-30

## Bağlam

Kanun metinleri bugünkü halleriyle indeksli. Dava dosyasındaki olay, bir hükmün sonradan
değiştiği bir tarihte olmuş olabilir. Örnek: fesih 2023'te, uygulanan fıkra 2024'te değişmiş.
O zaman olay tarihinde geçerli metin bugünkünden farklıydı. Bu sistem bunu hiç söylemiyordu.

mevzuat.gov.tr metinleri her değişikliği resmî bir notla gösterir, örneğin
`(Değişik ikinci cümle: 7/11/2024-7531/28 md.)`. Ayrıştırıcı bu notları derleme sırasında
`legal.provision_events` tablosuna yazıyordu. Her not türüyle (eklendi, değişti, mülga, AYM
iptali), tarihiyle, değiştiren kanunla ve bağlı olduğu madde, fıkra ya da bentle birlikte
tutuluyor; 2.000'den fazla kayıt var. Değişiklikten önceki metinler ise kaynaklarda yok.

## Karar

- **Notlar pasaja bağlanır.** Bir kanun pasajı, notun bağlı olduğu birimle metin aralığı
  kesişiyorsa o notu taşır (tek SQL sorgusu, cevap başına bir kez). Madde düzeyindeki bir not
  maddenin bütün pasajlarında, fıkra düzeyindeki bir not yalnız o fıkrayı içeren pasajda
  görünür. Notlar pasajın altında modele (`<amendments>`) ve doğrulayıcıya gider; kaynak
  panelinde "Değişiklik geçmişi" olarak listelenir.
- **Olay tarihini model bildirir, kod doğrular.** Sohbette cevap modeli `case_date` alanını,
  dosya analizinde konu çıkarma çağrısı her konu için `date` alanını doldurur. Ek bir Gemini
  çağrısı yoktur. Tarih yalnız dosya pasajlarında ya da kullanıcının mesajında aynen geçiyorsa
  kullanılır; model tarih uydurursa hiçbir karşılaştırma yapılmaz.
- **Karşılaştırmayı kod yapar, model değil.** Uyarı metni resmî notu olduğu gibi aktarır:
  - Olay tarihi değişiklikten önceyse uyarı çıkar: olay tarihinde hüküm yoktu, farklıydı ya da
    henüz yürürlükteydi.
  - Olay değişiklikten sonraki 6 ay içindeyse (AYM iptalinde 12 ay) yumuşak bir not çıkar.
    Nottaki tarih değişiklik kanununun kabul tarihidir; yürürlük daha sonra başlamış olabilir.
    Bilinen bir yürürlük tarihi varsa (`effective_from`) tahmin yerine o kullanılır.
- **Yalnız atıf yapılan pasajlar kontrol edilir.** Aynı not iki pasajda geçse de bir kez
  yazılır ve en fazla 8 uyarı gösterilir. Dosya analizinde her pasaj, onu bulan konunun
  tarihiyle karşılaştırılır; iki konu aynı pasajı bulduysa erken olan tarih esas alınır.

## Sonuç

Kullanıcı, bugünkü metne dayanan bir cevabın olay tarihinde farklı olabileceğini görür. Hangi
değişikliğin, ne zaman, hangi kanunla yapıldığını da resmî notuyla birlikte görür. Uyarı
hukuki bir hüküm değil, bir kontrol hatırlatmasıdır:

- Eski metni gösteremez.
- Geçiş hükümlerini (derdest davalara uygulanıp uygulanmadığını) bilmez.
- Kabul tarihi ile yürürlük tarihi arasındaki farkı yalnız yumuşak notla kapatır.

Web araması eski metni bulabileceği için bu durumda teklif kartı çıkar (ADR 0004,
`provision_changed`). Notların sorgusu başarısız olursa cevap notsuz devam eder.

## Güncelleme (2026-10-01): Yargıtay kararlarının güncelliği

Kontrol yalnız kanun pasajlarına bakıyordu. Oysa bir Yargıtay kararı, dayandığı madde sonradan
değiştiyse o maddenin eski haline göre verilmiştir. Örnek: 2012–2015 işe iade kararları,
İş Kanunu m.21'e 2017'de 7036 sayılı Kanunla fıkra eklenmeden önce verildi. 2023 kararlarının
bir kısmı ise 16.07.2026'da yürürlükten kaldırılan HMK m.107'ye dayanıyor.

- **Kararın dayandığı maddeler metinden okunur.** Atıf kalıpları: "4857 sayılı İş Kanunu'nun
  21 inci maddesinin beşinci fıkrası", "Türk Borçlar Kanunu'nun ... kenar başlıklı 400 üncü
  maddesi", "İŞ KANUNU (4857) Madde 21", "Kanun'un 25 inci maddesi".
- **Kural kesinlikten yanadır; emin olunmayan atıf alınmaz.** Bir madde numarası ancak
  kaynağımızın tanıyabildiği bir kanunun hemen ardından gelirse sayılır.
  - Adıyla anılan bir kanun, yürürlüğe girmeden önce verilmiş kararlarda sayılmaz (2013'teki
    "İş Mahkemeleri Kanunu" 5521'dir).
  - Yabancı kanunlar ("Rusya Federasyonu İş Kanunu") ve HUMK alınmaz.
- **Kararın verildiği tarihten sonraki değişiklikler karşılaştırılır.** Bunun için kanun
  pasajlarında kullanılan değişiklik kayıtları kullanılır.
  - Karar belirli bir fıkraya dayanıyorsa başka bir fıkradaki değişiklik ya da maddeye eklenen
    bir fıkra sayılmaz.
  - Olay tarihi biliniyorsa yalnız olaydan önce yürürlüğe giren değişiklikler uyarı üretir: hem
    karar hem olay eski metin dönemindeyse karar olaya uygundur. Olay tarihi yoksa karar
    bugünkü metinle karşılaştırılır.
- **Karar metni ve maddelerin değişiklikleri cevap başına iki sorguyla gelir.**
  - Değişiklikler modele kararın altında `<cited_provision_changes>` olarak gider.
  - Kaynak panelinde "Dayandığı maddelerde karardan sonraki değişiklikler" bölümünde görünür.
  - Uyarı aynı "Yürürlük kontrolü" kutusunda `decision_outdated` olarak çıkar.

Canlı veride 49 kararın 194 farklı madde atfı okundu ve 12 karar için uyarı çıktı. Hepsi elle
gözden geçirildi. Bulunamayan atıflar uyarı üretmez; bu, yanlış uyarı vermekten iyidir.
