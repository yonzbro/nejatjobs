"""İlan kaynakları. Her yanıt güvenilmezdir: boyutu sınırlanır, doğrulanır, filtrelenir."""
import asyncio
import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any

import httpx

from models import JobPosting, is_internship, is_long_term

log = logging.getLogger(__name__)

USER_AGENT = "nejatjobs/0.1 (+https://github.com/yonzbro/nejatjobs)"
MAX_BYTES = 5_000_000
SLUG = re.compile(r"^[a-z0-9-]{1,50}$")
RETRIES = 3
RETRY_DELAY = 2.0  # saniye: 2, 4


def make_client(transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(10.0),
        headers={"User-Agent": USER_AGENT},
        follow_redirects=False,
        transport=transport,
    )


class BaseScraper(ABC):
    source: str

    def __init__(self, client: httpx.AsyncClient, slug: str, company: str) -> None:
        if not SLUG.fullmatch(slug):
            raise ValueError(f"invalid slug: {slug!r}")
        self.client = client
        self.slug = slug
        self.company = company

    async def _get_json(self, url: str, **params: str) -> Any:
        # Geçici hatalarda (429, 5xx, ağ) üstel bekleme ile en fazla 3 deneme; 4xx tekrar denenmez
        for attempt in range(RETRIES):
            try:
                return await self._get_json_once(url, **params)
            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                if attempt == RETRIES - 1 or (code != 429 and code < 500):
                    raise
            except httpx.TransportError:
                if attempt == RETRIES - 1:
                    raise
            await asyncio.sleep(RETRY_DELAY * 2**attempt)

    async def _get_json_once(self, url: str, **params: str) -> Any:
        async with self.client.stream("GET", url, params=params) as r:
            r.raise_for_status()  # 3xx dahil: yönlendirme takip edilmez
            body = bytearray()
            async for chunk in r.aiter_bytes():
                body += chunk
                if len(body) > MAX_BYTES:
                    raise ValueError("response too large")
        return json.loads(body)

    @abstractmethod
    async def fetch(self) -> list[JobPosting]: ...


class LeverScraper(BaseScraper):
    source = "lever"
    allowed_host = "jobs.lever.co"

    async def fetch(self) -> list[JobPosting]:
        data = await self._get_json(f"https://api.lever.co/v0/postings/{self.slug}", mode="json")
        if not isinstance(data, list):
            raise ValueError("unexpected Lever response shape")
        jobs = []
        for item in data:
            try:
                job = self._parse(item)
            except (ValueError, TypeError, AttributeError) as e:  # ValidationError ⊂ ValueError
                log.warning("%s: skipped posting (%s)", self.slug, type(e).__name__)
                continue
            if job:
                jobs.append(job)
        return jobs

    def _parse(self, item: dict) -> JobPosting | None:
        cats = item.get("categories") or {}
        title, commitment = item.get("text"), cats.get("commitment")
        if item.get("country") != "TR" or not is_internship(title, commitment):
            return None
        job = JobPosting(
            source=self.source,
            company=self.company,
            title=title,
            url=item.get("hostedUrl"),
            location=cats.get("location"),
            country="TR",
            posted_at=item.get("createdAt"),  # Lever: epoch ms, Pydantic çözer
            is_long_term=is_long_term(title, commitment, item.get("descriptionPlain")),
        )
        if job.url.host != self.allowed_host:
            raise ValueError("posting URL outside Lever")
        return job


async def scrape_all(scrapers: list[BaseScraper], concurrency: int = 2) -> list[JobPosting]:
    sem = asyncio.Semaphore(concurrency)

    async def run(s: BaseScraper) -> list[JobPosting]:
        async with sem:
            try:
                return await s.fetch()
            except (httpx.HTTPError, ValueError) as e:  # bir şirket çökerse diğerleri devam eder
                log.error("%s/%s failed (%s)", s.source, s.slug, type(e).__name__)
                return []

    results = await asyncio.gather(*(run(s) for s in scrapers))
    return [job for jobs in results for job in jobs]
