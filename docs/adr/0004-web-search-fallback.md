# ADR 0004: Kaynak bulunamayınca isteğe bağlı web araması

- **Durum:** Kabul edildi
- **Tarih:** 2026-09-28

## Bağlam

Mevzuat ve içtihat kaynaklarında dayanağı olmayan sorular (güncel tutarlar, yeni düzenlemeler,
niş konular) "kaynak bulunamadı" cevabıyla bitiyordu. Kullanıcıya bu durumda web'de aratma
seçeneği verilecekti. İlk plan Gemini'nin Google Search grounding özelliğiydi, ancak:

- Gemini 3.x Flash ve Flash-Lite modellerinde Google Search ücretsiz katmanda yok (fiyat
  sayfası: "Not available"; denemede 429). Ücretsiz grounding sunan 2.5 modelleri yeni
  kullanıcılara kapalı (404). Live modeli de aramayla kota hatası veriyor.
- Faturalandırma açılırsa projedeki tüm Gemini kullanımı ücretli fiyata geçer.
- Grounding sayfa metnini döndürmez; cümleler BekenAI'nin doğrulayıcısından geçirilemez ve
  Google'ın arama önerisi kutusunun gösterilmesi zorunludur.
- Modele araçsız "web'de ara" demek arama yapmaz; model hafızasından yazar ve bağlantı
  uydurabilir.

## Karar

Web araması Tavily Search API ile yapılır (ücretsiz plan: ayda 1.000 kredi, `advanced` arama
2 kredi). Tavily her sonuç için sayfadan kısa alıntılar döndürür; bunlar `SOURCE_WEB_*`
kanıtı olur ve mevzuat pasajlarıyla aynı cümle bazlı doğrulamadan geçer.

- Web araması kendiliğinden çalışmaz. Kaynaklı cevap `insufficient_evidence` ise ya da hiçbir
  atfı doğrulanamadıysa cevap `web_search_offered` işaretini taşır. Arayüz "Web'de ara"
  düğmesini yalnız bu işaret varsa ve sunucuda anahtar tanımlıysa (`GET /chat/capabilities`)
  gösterir.
- Düğme aynı soruyu `search_mode=web` ile yeni bir tur olarak gönderir. Tur, cevap ve her web
  atfı ayrıca etiketlenir; cevap "Web kaynaklı" rozetini ve resmî kaynak olmadığını söyleyen
  bir notu taşır.
- Arama sorgusu planlayıcıdan gelir ve kişi, şirket adı, tarih gibi dosya bilgilerini içermez.
  Kullanıcının dosya pasajları yalnız Gemini'ye gider, arama motoruna gitmez.
- Web atıfları üçüncü bir kapsamdır (`source_scope='web'`). Veritabanında karşılığı olan bir
  satır olmadığından bütünlük kontrolü, anlık görüntünün http(s) adresi ve doğrulanan alıntıyı
  taşımasını şart koşar.

## Sonuç

Özellik ücretsiz katmanda kalır ve web cevapları da cümle cümle doğrulanır. Bedeli ikinci bir
dış servis ve anahtardır. `TAVILY_API_KEY` tanımlı değilken seçenek görünmez ve `POST /chat`
web isteğini `503 web_search_unavailable` ile reddeder. Aylık kota dolarsa iş
`web_search_quota_exceeded` ile biter.

## Güncelleme (2026-09-29): web, cevabın yerine değil sonuna

Deploy sonrası görüldü ki arama her soruda 25 aday getirdiği için model çoğu zaman kısmen
ilgili pasajlara dayanıp "cevapladım" diyor; "Web'de ara" teklifi pratikte nadiren çıkıyordu.
Davranış şöyle değişti:

- Sohbet kutusuna doktrin anahtarı gibi bir "Web araması" anahtarı eklendi. Üstüne gelince ne
  yaptığını anlatan bir açıklama çıkar. Anahtar kapatılana kadar o sohbette açık kalır; yeni
  sohbet kapalı başlar. Kaynaksız cevabın altındaki teklif de duruyor.
- `search_mode=web` artık web'i kaynaklarımızın yerine koymaz. Her zamanki arama, cevap ve
  doğrulama aynen çalışır; web araması paralel yapılır. Model, ana cevabı (`blocks`) yalnız
  mevzuat, içtihat, doktrin ve dosya kaynaklarına, en alttaki web bölümünü (`web_blocks`) yalnız
  web sayfalarına dayandırır. Bu bölüm web'in ana cevabı destekleyip desteklemediğini, ondan
  farklı ya da onunla çelişen bir şey söyleyip söylemediğini yazar. Her iki taraftaki yabancı
  kaynak kimlikleri kodda atılır; iki bölüm de cümle cümle doğrulanır.
- Planlayıcı, bizim arama sorgusundan ayrı olarak kişi, şirket adı ve tarih içermeyen bir web
  sorgusu yazar. Planlayıcı düşerse web'e yalnız kullanıcının kendi mesajı gider.
- Web araması başarısız olursa ya da kota dolarsa cevap yine gelir, web bölümü nedenini
  söyleyen kısa bir not olur. Web'de bir şey çıkmazsa da bunu söyleyen bir not görünür.
- Ek Gemini çağrısı yoktur: iki bölüm tek cevap çağrısında yazılır.

