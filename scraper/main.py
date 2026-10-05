import asyncio
import logging
import os

import httpx

from database import upsert_jobs
from models import JobPosting
from scraper import (
    AriTeknokentScraper,
    AshbyScraper,
    BaseScraper,
    GreenhouseScraper,
    LeverScraper,
    SmartRecruitersScraper,
    WorkdayScraper,
    make_client,
    scrape_all,
)

# Takip listesi: (kaynak, slug, görünen ad). Slug'lar şirketin ilan panosu URL'sinden alınır.
COMPANIES = [
    (LeverScraper, "trendyol", "Trendyol"),
    (LeverScraper, "insiderone", "Insider One"),
    (LeverScraper, "iyzico", "iyzico"),
    (LeverScraper, "dreamgames", "Dream Games"),
    (LeverScraper, "commencis", "Commencis"),
    (LeverScraper, "loopgames", "Loop Games"),
    (LeverScraper, "picus", "Picus Security"),
    (GreenhouseScraper, "goodjobgames", "Good Job Games"),
    (GreenhouseScraper, "constructortech", "Constructor"),
    (GreenhouseScraper, "veeamsoftware", "Veeam"),
    (AshbyScraper, "biggergames", "Bigger Games"),
    (AshbyScraper, "voodoo", "Voodoo"),
    (AshbyScraper, "codeway", "Codeway"),
    (AshbyScraper, "agavegames", "Agave Games"),
    (SmartRecruitersScraper, "boschgroup", "Bosch"),
    (SmartRecruitersScraper, "lesaffre", "Lesaffre"),
    (SmartRecruitersScraper, "reload1", "Reload"),
    (SmartRecruitersScraper, "averydennison", "Avery Dennison"),
    (SmartRecruitersScraper, "deliveryhero", "Delivery Hero"),
    # Teknopark portalı: şirket adı her ilanın kendi sayfasından alınır; bu ad yalnızca yedek
    (AriTeknokentScraper, "ari", "İTÜ ARI Teknokent"),
]
# Workday: (tenant, wd sunucusu, site) — kariyer sitesi URL'sinden: <tenant>.<wd>.myworkdayjobs.com/<site>
WORKDAY = [
    ("diageo", "wd3", "Diageo_Careers", "Diageo"),
    ("db", "wd3", "DBWebsite", "Deutsche Bank"),
    ("analogdevices", "wd1", "External", "Analog Devices"),
    ("pernodricard", "wd3", "pernod-ricard", "Pernod Ricard"),
]
TELEGRAM_LIMIT = 4000  # Telegram mesaj sınırı 4096


def format_messages(jobs: list[JobPosting]) -> list[str]:
    # Düz metin: parse_mode yok → ilan başlığındaki HTML/Markdown yorumlanmaz (injection yok)
    blocks = [("🔥 UZUN DÖNEM\n" if j.is_long_term else "") + f"{j.company} | {j.title}\n{j.url}" for j in jobs]
    messages, current = [], ""
    for b in blocks:
        if current and len(current) + len(b) + 2 > TELEGRAM_LIMIT:
            messages.append(current)
            current = ""
        current = f"{current}\n\n{b}" if current else b
    return messages + [current] if current else messages


async def notify(client: httpx.AsyncClient, jobs: list[JobPosting]) -> None:
    token, chat_id = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat_id and jobs):
        return
    for text in format_messages(jobs):
        r = await client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        )
        if r.is_error:
            # raise_for_status() kullanılmaz: hata mesajı URL'yi, yani token'ı içerir
            raise RuntimeError(f"Telegram sendMessage failed: HTTP {r.status_code}")


async def main() -> None:
    async with make_client() as client:
        scrapers: list[BaseScraper] = [cls(client, slug, name) for cls, slug, name in COMPANIES]
        scrapers += [WorkdayScraper(client, t, name, wd, site) for t, wd, site, name in WORKDAY]
        jobs = await scrape_all(scrapers)
        # Supabase ayarlı değilse yalnızca listeler (yerel deneme)
        new = await upsert_jobs(client, jobs) if os.environ.get("SUPABASE_URL") else set()
        await notify(client, [j for j in jobs if j.dedup_hash in new])
    for j in jobs:
        tags = ("[YENİ] " if j.dedup_hash in new else "") + ("[UZUN] " if j.is_long_term else "")
        tags += "[MEZUN] " if j.is_new_grad else ""
        print(f"{tags}{j.company} | {j.title} | {j.url}")
    print(f"{len(jobs)} TR ilanı (staj + yeni mezun), {len(new)} yeni")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # httpx istek URL'sini loglar → Telegram token sızar
    asyncio.run(main())
