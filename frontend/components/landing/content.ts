import type { IconName } from '@/components/icons';

export const HERO_FACTS = ['Hibrit arama', 'İddia bazlı doğrulama', 'Sürümlü kaynak kaydı'];

export const TECH = [
  ['Next.js', 'Arayüz'],
  ['React', 'Bileşenler'],
  ['Tailwind CSS', 'Stil sistemi'],
  ['FastAPI', 'API ve worker'],
  ['PostgreSQL', 'Sürümlü hukuk şeması'],
  ['Supabase', 'Kimlik, veri, depolama'],
  ['Qdrant', 'Vektör arama'],
  ['BM25', 'Anahtar kelime arama'],
  ['BGE-M3', 'Çok dilli gömme modeli'],
  ['BGE Reranker v2', 'Yeniden sıralama'],
  ['Gemini', 'Yazım ve doğrulama'],
  ['Oracle Cloud', 'Barındırma'],
] as const;

export const METRICS = [
  ['6', 'aşamalı cevap hattı: toplamadan doğrulamaya'],
  ['25', 'aday pasaj, her soru için yeniden sıralanır'],
  ['1024', 'boyutlu anlam vektörleri (BGE-M3)'],
  ['150+', 'otomatik test, CI’da her değişiklikte çalışır'],
] as const;

export const APPROACHES = [
  {
    title: 'Yalnızca dil modeli',
    flow: ['Soru', 'Model', 'Cevap'],
    body: 'Cevabı eğitim sırasında öğrendiklerinden üretir. Kaynak göstermez; yanlış bir bilgiyi de aynı özgüvenle yazabilir. Buna halüsinasyon denir.',
    verdict: 'Kaynak yok · halüsinasyon riski yüksek',
    tone: 'err',
  },
  {
    title: 'Klasik RAG',
    flow: ['Soru', 'Arama', 'Kaynaklar', 'Model', 'Cevap'],
    body: 'Önce ilgili belgeleri bulur, cevabı onlara dayanarak yazar ve kaynak gösterir. Ancak her cümlenin gerçekten kaynakta yazıp yazmadığını ayrıca kontrol etmez.',
    verdict: 'Kaynak var · cümleler kontrol edilmez',
    tone: 'neutral',
  },
] as const;

export const OUR_STEPS: { title: string; phase: 'arama' | 'seçim' | 'yazım' | 'doğrulama'; body: string }[] = [
  { title: 'Sorgu hazırlama', phase: 'arama', body: 'Uzun mesajlarda soru cümleleri ve hukuki terimler öne alınarak en fazla 500 karakterlik bir arama sorgusu çıkarılır.' },
  { title: 'Anahtar kelime araması', phase: 'arama', body: 'BM25; “ihbar”, “fesih” gibi terimleri birebir eşleştirir.' },
  { title: 'Anlam araması', phase: 'arama', body: 'BGE-M3 vektörleri, farklı kelimelerle sorulan aynı soruyu da yakalar.' },
  { title: 'RRF birleştirme', phase: 'arama', body: 'İki sıralama, pasajların konumlarına göre tek listede birleştirilir.' },
  { title: 'Yeniden sıralama', phase: 'seçim', body: 'En iyi 25 aday, soruyla birlikte okunarak yeniden puanlanır.' },
  { title: 'Bağlam seçimi', phase: 'seçim', body: 'Pasajlar token bütçesine göre seçilir; hiç birincil kaynak sığmazsa cevap üretilmez.' },
  { title: 'Yapılandırılmış yazım', phase: 'yazım', body: 'Model her iddiayı, dayandığı kaynak kimlikleriyle birlikte JSON şemasına göre yazar.' },
  { title: 'Atıf bütünlüğü', phase: 'yazım', body: 'Var olmayan ya da yanlış kanaldan kaynak gösteren cevap reddedilir ve yedek modelle yeniden yazılır.' },
  { title: 'İddia doğrulama', phase: 'doğrulama', body: 'Her iddia–pasaj çifti ayrı bir modelle “destekliyor”, “kısmen” veya “desteklemiyor” olarak etiketlenir.' },
  { title: 'Filtreleme ve kayıt', phase: 'doğrulama', body: 'Desteklenmeyen iddialar atılır; cevap atıflar ve kaynak sürümleriyle kaydedilir. Hiç iddia kalmazsa “yeterli kaynak yok” döner.' },
];

export const PIPELINE = [
  {
    title: 'Kaynakları toplar',
    en: 'Ingestion',
    plain: 'Kanunlar, Yargıtay kararları ve doktrin sisteme yüklenir. Her güncelleme ayrı bir sürüm olarak saklanır; eski bir cevabın hangi kaynağa dayandığı kaybolmaz.',
    tech: 'Manifest tabanlı içe aktarma, içerik hash’iyle tekrar kontrolü ve değiştirilemez ham belge deposu. Meta veriler sürümlü bir PostgreSQL şemasında tutulur.',
    tags: ['Python', 'Supabase Storage', 'PostgreSQL'],
  },
  {
    title: 'Metni parçalara ayırır',
    en: 'Chunking',
    plain: 'Belgeler madde, fıkra ve bent yapısı korunarak küçük parçalara bölünür. Böylece cevap belgenin tamamına değil, tam ilgili pasaja işaret eder.',
    tech: 'Hukuki yapıyı tanıyan ayrıştırıcı; her parça künye, madde yolu ve sayfa bilgisini taşır. Madde değişiklikleri ayrı sürümler olarak izlenir.',
    tags: ['Yapı farkında parser', 'Madde sürümleri'],
  },
  {
    title: 'İlgili pasajları bulur',
    en: 'Hybrid retrieval',
    plain: 'Soru hem kelime kelime hem de anlamca aranır. “İşten çıkarıldım” diye soran biri, “fesih” geçen maddeyi de bulur.',
    tech: 'BM25 anahtar kelime araması ile BGE-M3 yoğun vektör araması birlikte çalışır; sonuçlar Reciprocal Rank Fusion (k=60) ile birleştirilir.',
    tags: ['BM25', 'BGE-M3', 'Qdrant', 'RRF'],
  },
  {
    title: 'En alakalıları seçer',
    en: 'Reranking',
    plain: 'Bulunan 25 aday pasaj daha güçlü bir modelle tek tek puanlanır; soruya en iyi cevap veren pasajlar öne çıkar.',
    tech: 'Cross-encoder ile yeniden sıralama. Gömme ve sıralama modelleri, yalnızca iç ağdan erişilen ayrı bir model servisinde çalışır.',
    tags: ['bge-reranker-v2-m3', 'Model servisi'],
  },
  {
    title: 'Kaynaklara dayanarak yazar',
    en: 'Generation',
    plain: 'Dil modeli yalnızca seçilen pasajları görür ve cevabı, her biri kaynağına bağlı kısa iddialar halinde yazar.',
    tech: 'JSON şemalı yapılandırılmış çıktı ve token bütçesine göre bağlam seçimi. Geçici hatada yedek modele geçilir; kaynak metinleri güvenilmeyen veri olarak işaretlenir (prompt injection koruması).',
    tags: ['Gemini', 'Structured output', 'Pydantic'],
  },
  {
    title: 'Her iddiayı doğrular',
    en: 'Verification',
    plain: 'Ayrı bir model, her iddianın gerçekten kaynağında yazıp yazmadığını kontrol eder. Desteklenmeyen iddia silinir; hiç iddia kalmazsa sistem “yeterli kaynak yok” der.',
    tech: 'Her iddia–pasaj çifti supported, partial veya unsupported olarak sınıflandırılır. Atıf bütünlüğü kontrolü geçersiz kaynak kimliklerini reddeder.',
    tags: ['Claim verification', 'insufficient_evidence'],
  },
];

export const JOURNEY = [
  { where: 'Tarayıcı · Next.js', title: 'Soru gönderilir', body: 'Arayüz soruyu API’ye iletir ve işin hangi adımda olduğunu canlı olarak gösterir.', tech: 'React 19 · Tailwind 4' },
  { where: 'API · FastAPI', title: 'İstek kabul edilir', body: 'Kimlik doğrulanır, soru kuyruğa eklenir ve kullanıcıya hemen “sırada” yanıtı döner.', tech: '202 Accepted · Idempotency-Key' },
  { where: 'İş kuyruğu · PostgreSQL', title: 'İş sıraya girer', body: 'Aynı soru iki kez işlenmez. Bir hata olursa iş otomatik olarak yeniden denenir.', tech: 'en fazla 2 deneme · takılı iş kurtarma' },
  { where: 'Worker', title: 'Cevap üretilir', body: 'Arama, yazım ve doğrulama arka planda çalışır; kullanıcı sayfayı kapatsa bile iş devam eder.', tech: 'Qdrant · model servisi · Gemini' },
  { where: 'Veritabanı', title: 'Sonuç kaydedilir', body: 'Cevap, atıflar ve kullanılan kaynak sürümleri birlikte saklanır; bir cevabın dayanağı sonradan izlenebilir.', tech: 'corpus_version · index_version' },
];

export const ADRS = [
  { id: 'ADR 0001', title: 'Modüler monolit', body: 'Tek geliştirici için mikroservis yükü gereksizdi. Uygulama tek parça dağıtılır, ama arama, içe aktarma ve API ayrı paketlerdir; gerektiğinde ayrılabilir.' },
  { id: 'ADR 0002', title: 'Ortak ve özel veri sınırı', body: 'Kullanıcı dosyaları ile ortak hukuk kaynakları ayrı depolama ve vektör sınırlarında tutulur. Bir müvekkil belgesinin başkasının cevabına karışması mimari olarak engellenir.' },
  { id: 'ADR 0003', title: 'Model sağlayıcıdan bağımsızlık', body: 'Dil modeli çağrıları bir arayüzün arkasındadır. Model ya da sağlayıcı değişse bile arama ve atıf çekirdeği aynı kalır.' },
];

export const GLOSSARY = [
  ['RAG', 'Retrieval-Augmented Generation. Modelin cevap yazmadan önce ilgili belgeleri bulup onlara dayanması.'],
  ['Halüsinasyon', 'Dil modelinin gerçekte olmayan bir bilgiyi kendinden emin biçimde üretmesi.'],
  ['Embedding', 'Metnin anlamını sayılara çeviren temsil. Benzer anlamlı metinler birbirine yakın düşer.'],
  ['Vektör veritabanı', 'Bu sayısal temsiller arasında en yakın olanları hızla bulan veritabanı. Burada Qdrant.'],
  ['Reranker', 'Bulunan adayları soruyla birlikte okuyup yeniden puanlayan, daha hassas model.'],
] as const;

export const COVERAGE = [
  { title: 'Mevzuat', tone: 'bg-accent', items: ['İş Kanunu', 'Kıdem tazminatı düzenlemesi', 'İş Mahkemeleri Kanunu', 'Türk Borçlar Kanunu', 'Hukuk Muhakemeleri Kanunu', 'Arabuluculuk Kanunu'] },
  { title: 'İçtihat', tone: 'bg-fg2', items: ['Yargıtay kararları', 'İş hukuku uyuşmazlıkları'] },
  { title: 'Doktrin', tone: 'bg-doc', items: ['İzinli iş hukuku ders notu', 'Birincil kaynaklardan ayrı kanalda'] },
];

export const SECURITY: { icon: IconName; title: string; body: string }[] = [
  { icon: 'key', title: 'Google ile giriş', body: 'Kimlik doğrulama Supabase Auth ile yapılır; her istekteki token imzası sunucuda doğrulanır.' },
  { icon: 'box', title: 'Çalışma alanı izolasyonu', body: 'Her özel kayıt bir çalışma alanına bağlıdır; sorgular bu sınırın dışına çıkamaz.' },
  { icon: 'shield', title: 'Ortak havuza karışmaz', body: 'Davalara yüklenen dosyalar ortak kaynak dizinine hiçbir zaman yazılmaz.' },
  { icon: 'lock', title: 'Doğrulanmış bağlantılar', body: 'Veritabanı bağlantıları TLS ve tam sertifika doğrulamasıyla kurulur.' },
  { icon: 'pin', title: 'Sabitlenmiş bağımlılıklar', body: 'Paketler hash ile kilitlidir; CI her değişiklikte güvenlik taraması çalıştırır.' },
  { icon: 'eyeOff', title: 'Sızıntısız kayıtlar', body: 'Özel dosya yolları ve istek adresleri uygulama kayıtlarına yazılmaz.' },
];

export const LIMITS = [
  'Yalnızca iş hukuku kapsanıyor; diğer alanlar henüz yok.',
  'Doğrulama adımları nedeniyle bir cevap 1–2 dakika sürebilir.',
  'Altyapı tek kullanıcılı demo için boyutlandırıldı.',
  'Taranmış (görüntü) PDF’ler okunmaz; metin katmanı olan PDF, Word (DOCX) veya TXT gerekir.',
  'Cevaplar araştırma amaçlıdır; hukuki danışmanlık değildir.',
];

export const FAQ = [
  { q: 'Bu gerçek bir ürün mü?', a: 'Hayır. BekenAI bir demo ve portföy projesidir. Arama ve doğrulama hattı gerçek kaynaklarla çalışır, ancak ticari bir hizmet sunulmaz.' },
  { q: 'Hangi kaynakları kullanıyor?', a: 'İş hukukuna ilişkin kanunlar, Yargıtay kararları, izinli doktrin kaynakları ve sizin yüklediğiniz dosyalar. Her cevapta kullanılan kaynaklar ve sürümleri gösterilir.' },
  {
    q: 'Kendi dosyamı yükleyebilir miyim?',
    a: 'Evet. Bir sohbete ya da davaya PDF, Word (DOCX) veya TXT ekleyebilirsiniz. Dosya işlendikten sonra sorular dosyadaki pasaja sayfa atfıyla cevaplanır; dosyada yazanlar mevzuat ve içtihattan ayrı bir bölümde gösterilir. Dosyalar yalnızca sizin çalışma alanınızda tutulur. Elinizde dosya yoksa demo bölümündeki kurgusal örnek dava dosyasını kullanabilirsiniz.',
  },
  { q: 'Cevap bulamazsa ne olur?', a: 'Soruyu destekleyen yeterli birincil kaynak yoksa BekenAI cevap üretmez ve bunu açıkça belirtir.' },
  { q: 'Cevap neden birkaç dakika sürebiliyor?', a: 'Her iddia ayrı bir doğrulama adımından geçer. Bekleme sırasında işin hangi adımda olduğunu görürsünüz.' },
];
