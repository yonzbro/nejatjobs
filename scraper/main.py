import asyncio
import logging

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
    for j in jobs:
        print(f"{'[UZUN] ' if j.is_long_term else ''}{j.company} | {j.title} | {j.url}")
    print(f"{len(jobs)} TR staj ilanı")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
