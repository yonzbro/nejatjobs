import asyncio
import logging
import os

from database import upsert_jobs
from scraper import LeverScraper, make_client, scrape_all

LEVER_COMPANIES = {
    "trendyol": "Trendyol",
    "insiderone": "Insider One",
    "iyzico": "iyzico",
    "dreamgames": "Dream Games",
}


async def main() -> None:
    async with make_client() as client:
        jobs = await scrape_all([LeverScraper(client, s, n) for s, n in LEVER_COMPANIES.items()])
        # Supabase ayarlı değilse yalnızca listeler (yerel deneme)
        new = await upsert_jobs(client, jobs) if os.environ.get("SUPABASE_URL") else set()
    for j in jobs:
        tags = ("[YENİ] " if j.dedup_hash in new else "") + ("[UZUN] " if j.is_long_term else "")
        print(f"{tags}{j.company} | {j.title} | {j.url}")
    print(f"{len(jobs)} TR staj ilanı, {len(new)} yeni")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
