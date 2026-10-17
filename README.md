# nejatjobs

**Türkiye'deki uzun dönem staj, staj ve yeni mezun ilanlarını tek sayfada toplayan, ücretsiz ve açık kaynak bir takip sistemi.**

🔗 **Canlı site: [nejatjobs.vercel.app](https://nejatjobs.vercel.app/)**

> Günde 3 kez şirketlerin kariyer sistemlerini tarar, yeni ilanları veritabanına yazar ve tek bir listede gösterir. Uzun dönem stajlar ayrıca etiketlenir.

---

## Neden yaptım?

Uzun dönem staj ararken her gün aynı rutini yaşıyordum: Trendyol'un kariyer sayfası, Insider'ın Lever panosu, Bosch'un SmartRecruiters'ı, teknoparkların portalları… Onlarca sekme açıyor, aynı ilanları tekrar tekrar görüyor, yenisini çoğu zaman da kaçırıyordum. Üstelik "uzun dönem" ifadesi ilan başlıklarında nadiren geçiyor. Bu bilgi genelde açıklamanın içinde "haftada 3 gün" ya da "6 ay" gibi ifadelerin arasında kalıyor.

Bu yüzden önce kendim için küçük bir tarayıcı yazdım. Bulduğum ilanları paylaştıkça arkadaşlarımdan sürekli aynı mesaj gelmeye başladı: *"Kanka bizle de paylaş."* Ekran görüntüsü atmak yerine herkesin açıp bakabileceği bir site yapmaya karar verdim. nejatjobs böyle doğdu.

## Neden bu şekilde? (ve neden daha fazlası değil)

İdeal dünyada Youthall, Toptalent, LinkedIn ve Kariyer.net dahil her yerdeki ilanları tek yerde toplamak isterdim. Ama gerçek şu:

- **Açık API çoğu yerde yok.** Türkiye'deki popüler staj platformlarının herkese açık bir API'si yok.
- **Kullanım koşulları izin vermiyor.** Youthall, Toptalent gibi siteler içeriğin kopyalanmasını ve yeniden yayınlanmasını açıkça yasaklıyor. Public bir sitede bu ilanları göstermek hem etik hem hukuki açıdan sorunlu.
- **Bot korumaları ve `robots.txt`.** Bazı teknoparklar Cloudflare arkasında, bazıları `robots.txt` ile tarayıcıları engelliyor, bazıları ise giriş istiyor. Bu korumaları aşmak bu projenin kapsamında değil.

Bu yüzden proje bilinçli olarak **"izin verilen yerden veri çek, gerisini linkle"** yaklaşımıyla tasarlandı:

| Yöntem | Kaynaklar |
| --- | --- |
| **Otomatik çekilir** (şirketlerin herkese açık ATS uç noktaları) | Lever, Greenhouse, Ashby, SmartRecruiters, Workday, İTÜ ARI Teknokent portalı |
| **Yalnızca link verilir** (veri çekilmez) | Youthall, Toptalent, anbean KAMPÜS, Kariyer.net, LinkedIn, Teknopark İstanbul, ODTÜ, Yıldız, Sakarya, Kocaeli, GTÜ, Ulutek |

Daha kapsamlı olabilirdi, ama bu haliyle **sıfır maliyetli, yasal açıdan temiz ve sürdürülebilir.**

> **Not:** SmartRecruiters ve Workday için `robots.txt` / resmi API kuralına bilinçli bir istisna yapıldı. Yalnızca herkese açık ilanlar okunuyor, istek sayısı günde 3 ile sınırlı ve User-Agent açıkça belirtiliyor. Bir şirket ya da platform itiraz ederse kaynak kaldırılır.

---

## Özellikler

- 🔁 **Otomatik güncelleme:** GitHub Actions ile günde 3 kez (TR saatiyle 08:17, 14:17, 20:17)
- 🏷️ **Akıllı etiketleme:** `uzun dönem` (6 ay, part-time intern, "haftada N gün", Bosch Smart Start…) ve `yeni mezun` (New Grad, Fresh Grad, Management Trainee) ilanları ayrı işaretlenir
- 🇹🇷 **Yalnızca Türkiye:** Global şirketlerin yurt dışı ilanları elenir
- 🔎 **Filtreleme:** Şirket ve ilan türüne göre (staj / uzun dönem / yeni mezun), JavaScript gerektirmeden
- 📣 **Telegram bildirimi (opsiyonel):** Yeni ilan geldiğinde kanala mesaj düşer
- 🧹 **Tekilleştirme:** Aynı ilan iki kez yazılmaz (SHA-256 hash + `ON CONFLICT`)
- 💸 **Tamamen ücretsiz altyapı:** GitHub Actions + Supabase free tier + Vercel Hobby

## Takip edilen şirketler

Trendyol · Insider One · iyzico · Dream Games · Commencis · Loop Games · Picus Security · Good Job Games · Constructor · Veeam · Bigger Games · Voodoo · Codeway · Agave Games · Bosch · Lesaffre · Reload · Avery Dennison · Delivery Hero · Diageo · Deutsche Bank · Analog Devices · Pernod Ricard · Citi · Mastercard · P&G · Novartis · Unilever · Roche · AstraZeneca · Pfizer · Abbott · Johnson & Johnson · Philips · Coca-Cola · Mondelēz · Mars · Shell · Maersk · Thales · Intel · HP · İTÜ ARI Teknokent firmaları

Yeni şirket eklemek tek satırlık iş (bkz. [Katkı](#katkı)).

---

## Mimari

```
┌──────────────────────┐    günde 3x     ┌─────────────────────┐
│  GitHub Actions cron │ ──────────────▶ │  Python scraper     │
│  (önce güvenlik      │                 │  httpx + Pydantic   │
│   testleri koşar)    │                 │  Lever/GH/Ashby/... │
└──────────────────────┘                 └──────────┬──────────┘
                                                    │ upsert (secret key)
                                                    ▼
┌──────────────────────┐   SELECT only   ┌─────────────────────┐
│  Next.js (Vercel)    │ ◀────────────── │  Supabase Postgres  │
│  Server Components   │ (publishable +  │  + Row Level        │
│                      │       RLS)      │    Security         │
└──────────────────────┘                 └─────────────────────┘
```

| Katman | Teknoloji | Neden |
| --- | --- | --- |
| Veri toplama | Python 3.13, `httpx` (async), Pydantic v2, BeautifulSoup4 | Asenkron istekler, timeout ve retry/backoff; dış veriye katı şema doğrulaması |
| Veritabanı | Supabase (PostgreSQL) | Ücretsiz katman, RLS ile satır seviyesinde yetki |
| Zamanlama | GitHub Actions cron | Public repoda ücretsiz, secret yönetimi hazır |
| Arayüz | Next.js 16, React 19, düz CSS | Sunucu tarafı render, istemciye secret sızmaz |
| Test | pytest, Vitest | Scraper, RLS ve web katmanı güvenlik testleri |

## Güvenlik

Proje herkese açık ve dış kaynaklardan gelen veriyi gösteriyor. Bu yüzden güvenlik baştan tasarımın bir parçası olarak ele alındı:

- **RLS:** Frontend'deki publishable key yalnızca `SELECT` yapabilir. Yazma yetkisi yalnızca GitHub Actions'taki secret key'de.
- **Her çalışmada test:** Cron, scraper'dan önce güvenlik testlerini çalıştırır. RLS bozulursa scraper hiç çalışmaz.
- **XSS / link güvenliği:** İlan URL'leri hem Pydantic'te hem arayüzde yalnızca `http/https` şemasına izin verir (`javascript:` linkleri engellenir). `dangerouslySetInnerHTML` hiç kullanılmaz.
- **SSRF koruması:** Her kaynakta ilan linki yalnızca o platformun kendi host'una izinli. Teknopark portalı dışındaki linklere istek atılmaz.
- **HTTP başlıkları:** Nonce tabanlı CSP, `X-Frame-Options`, `nosniff`, Referrer ve Permissions Policy.
- **Tabnabbing:** Dış linklerde `rel="noopener noreferrer"` kullanılır.
- **Supply chain:** GitHub Actions adımları tag ile değil, commit SHA'sı ile sabitlenir. `GITHUB_TOKEN` salt okunurdur.
- **Nazik tarama:** Açık User-Agent, istekler arası bekleme, sayfalama sınırı. Bot korumalarını aşmaya yönelik hiçbir teknik kullanılmaz.

---

## Kendi kopyanı çalıştır

### Gereksinimler
- Python 3.11+
- Node.js 20+
- Ücretsiz bir [Supabase](https://supabase.com) projesi

### 1. Veritabanı
Supabase SQL Editor'de [`scraper/schema.sql`](scraper/schema.sql) dosyasını çalıştır. Tablo ve RLS politikaları oluşur.

### 2. Ortam değişkenleri
```bash
cp .env.example .env
# SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, SUPABASE_SECRET_KEY değerlerini doldur
# (Telegram değişkenleri opsiyonel)
```
> ⚠️ `SUPABASE_SECRET_KEY` asla `NEXT_PUBLIC_` önekiyle frontend'e verilmez.

### 3. Scraper
```bash
cd scraper
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest -q      # güvenlik testleri
python main.py           # ilanları çek ve yaz
```

### 4. Web
```bash
cd web
npm install
npm run dev              # http://localhost:3000
npm test                 # Vitest güvenlik testleri
```

### 5. Otomasyon
Repo → **Settings → Secrets and variables → Actions** altına `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY` (ve isteğe bağlı `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) ekle. Workflow ([`.github/workflows/scraper.yml`](.github/workflows/scraper.yml)) kendiliğinden çalışmaya başlar. Actions sekmesinden elle de tetiklenebilir.

> Public repolarda 60 gün commit olmazsa GitHub cron workflow'larını otomatik durdurur.

---

## Katkı

En değerli katkı **yeni şirket eklemek.** Şirketin kariyer sayfası Lever, Greenhouse, Ashby, SmartRecruiters ya da Workday kullanıyorsa [`scraper/main.py`](scraper/main.py) içindeki listeye bir satır eklemen yeterli:

```python
(LeverScraper, "sirket-slug", "Şirket Adı"),
# Workday için: ("tenant", "wd3", "SiteAdi", "Şirket Adı")
```

Slug, şirketin ilan panosu URL'sinde yazar (örn. `jobs.lever.co/trendyol` → `trendyol`).

"Uzun dönem" olarak işaretlenmesi gerekirken kaçan bir ilan kalıbı gördüysen issue açabilirsin. Anahtar kelime listesi zamanla büyüyor.

## Sorumluluk reddi

Bu proje kişisel ve kâr amacı gütmeyen bir araçtır. İlanların tüm hakları ilgili şirketlere aittir. Her ilan kartı doğrudan şirketin kendi başvuru sayfasına yönlendirir. Kaldırılmasını istediğiniz bir kaynak varsa lütfen issue açın; kaynak en kısa sürede kaldırılır.

---

<p align="center">Staj arayan herkese kolay gelsin 🎓</p>
