"""İlan kaynakları. Her yanıt güvenilmezdir: boyutu sınırlanır, doğrulanır, filtrelenir."""
import asyncio
import json
import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

from models import JobPosting, is_internship, is_long_term, is_new_grad, is_turkey

log = logging.getLogger(__name__)

USER_AGENT = "nejatjobs/0.1 (+https://github.com/yonzbro/nejatjobs)"
MAX_BYTES = 5_000_000
SLUG = re.compile(r"^[a-z0-9-]{1,50}$")
RETRIES = 3
RETRY_DELAY = 2.0  # saniye: 2, 4
MAX_PAGES = 10  # sayfalı API'lerde sonsuz döngü / aşırı istek sigortası


def make_client(transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(10.0),
        headers={"User-Agent": USER_AGENT},
        follow_redirects=False,
        transport=transport,
    )


class BaseScraper(ABC):
    source: str
    allowed_hosts: frozenset[str]  # ilan linki bu host'lardan biri değilse ilan atılır (oltalama linki)

    def __init__(self, client: httpx.AsyncClient, slug: str, company: str) -> None:
        if not SLUG.fullmatch(slug):
            raise ValueError(f"invalid slug: {slug!r}")
        self.client = client
        self.slug = slug
        self.company = company

    async def _json(self, url: str, body: dict | None = None, **params: str) -> Any:
        return json.loads(await self._fetch(url, body, **params))

    async def _fetch(self, url: str, body: dict | None = None, **params: str) -> bytes:
        # Geçici hatalarda (429, 5xx, ağ) üstel bekleme ile en fazla 3 deneme; 4xx tekrar denenmez
        for attempt in range(RETRIES):
            try:
                return await self._fetch_once(url, body, **params)
            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                if attempt == RETRIES - 1 or (code != 429 and code < 500):
                    raise
            except httpx.TransportError:
                if attempt == RETRIES - 1:
                    raise
            await asyncio.sleep(RETRY_DELAY * 2**attempt)

    async def _fetch_once(self, url: str, body: dict | None, **params: str) -> bytes:
        method = "GET" if body is None else "POST"
        async with self.client.stream(method, url, params=params, json=body) as r:
            r.raise_for_status()  # 3xx dahil: yönlendirme takip edilmez
            data = bytearray()
            async for chunk in r.aiter_bytes():
                data += chunk
                if len(data) > MAX_BYTES:
                    raise ValueError("response too large")
        return bytes(data)

    async def fetch(self) -> list[JobPosting]:
        jobs = []
        for item in await self._items():
            try:
                job = self._parse(item)
            except (ValueError, TypeError, AttributeError, KeyError) as e:  # ValidationError ⊂ ValueError
                log.warning("%s/%s: skipped posting (%s)", self.source, self.slug, type(e).__name__)
                continue
            if job:
                jobs.append(job)
        return jobs

    @abstractmethod
    async def _items(self) -> list: ...

    @abstractmethod
    def _parse(self, item: dict) -> JobPosting | None: ...

    def _job(
        self,
        *,
        title: str,
        url: str,
        location: str | None,
        posted_at: Any = None,
        labels: tuple[str | None, ...] = (),  # kaynağın kendi "Intern" / "Part-time" gibi alanları
        description: str | None = None,
        company: str | None = None,  # çok şirketli kaynaklarda (teknopark portalı) ilanın kendi şirketi
    ) -> JobPosting | None:
        """TR'deki ilanın staj / yeni mezun olup olmadığına karar verir ve doğrular."""
        new_grad = is_new_grad(title, *labels)
        if not (new_grad or is_internship(title, *labels)):
            return None
        job = JobPosting(
            source=self.source,
            company=company or self.company,
            title=title,
            url=url,
            location=location,
            country="TR",
            posted_at=posted_at,
            is_long_term=is_long_term(title, *labels, description),
            is_new_grad=new_grad,
        )
        if job.url.host not in self.allowed_hosts:
            raise ValueError("posting URL outside allowed hosts")
        return job


def _expect(data: Any, key: str | None = None) -> list:
    items = data.get(key) if key and isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("unexpected response shape")
    return items


class LeverScraper(BaseScraper):
    source = "lever"
    allowed_hosts = frozenset({"jobs.lever.co"})

    async def _items(self) -> list:
        return _expect(await self._json(f"https://api.lever.co/v0/postings/{self.slug}", mode="json"))

    def _parse(self, item: dict) -> JobPosting | None:
        cats = item.get("categories") or {}
        if item.get("country") != "TR":
            return None
        return self._job(
            title=item.get("text"),
            url=item.get("hostedUrl"),
            location=cats.get("location"),
            posted_at=item.get("createdAt"),  # Lever: epoch ms, Pydantic çözer
            labels=(cats.get("commitment"),),
            description=item.get("descriptionPlain"),
        )


class GreenhouseScraper(BaseScraper):
    source = "greenhouse"
    allowed_hosts = frozenset({"job-boards.greenhouse.io", "job-boards.eu.greenhouse.io", "boards.greenhouse.io"})

    async def _items(self) -> list:
        # ponytail: content=true açıklamayı da verir ama büyük panolarda ~5 MB; uzun dönem yalnızca başlıktan
        return _expect(await self._json(f"https://boards-api.greenhouse.io/v1/boards/{self.slug}/jobs"), "jobs")

    def _parse(self, item: dict) -> JobPosting | None:
        location = (item.get("location") or {}).get("name")
        if not is_turkey(location):
            return None
        return self._job(
            title=item.get("title"),
            url=item.get("absolute_url"),
            location=location,
            posted_at=item.get("first_published"),
        )


class AshbyScraper(BaseScraper):
    source = "ashby"
    allowed_hosts = frozenset({"jobs.ashbyhq.com"})

    async def _items(self) -> list:
        return _expect(await self._json(f"https://api.ashbyhq.com/posting-api/job-board/{self.slug}"), "jobs")

    def _parse(self, item: dict) -> JobPosting | None:
        address = ((item.get("address") or {}).get("postalAddress") or {}).get("addressCountry")
        if not item.get("isListed", True) or not is_turkey(address, item.get("location")):
            return None
        return self._job(
            title=item.get("title"),
            url=item.get("jobUrl"),
            location=item.get("location"),
            posted_at=item.get("publishedAt"),
            labels=(item.get("employmentType"),),
            description=item.get("descriptionPlain"),
        )


class SmartRecruitersScraper(BaseScraper):
    # Not: api.smartrecruiters.com robots.txt'si botları engelliyor; kullanıcı kararıyla eklendi (bkz. nejatjobs.md)
    source = "smartrecruiters"
    allowed_hosts = frozenset({"jobs.smartrecruiters.com"})
    PAGE = 100

    async def _items(self) -> list:
        items: list = []
        for page in range(MAX_PAGES):
            data = await self._json(
                f"https://api.smartrecruiters.com/v1/companies/{self.slug}/postings",
                country="tr", limit=str(self.PAGE), offset=str(page * self.PAGE),
            )
            batch = _expect(data, "content")
            items += batch
            if len(batch) < self.PAGE:
                break
        return items

    def _parse(self, item: dict) -> JobPosting | None:
        loc = item.get("location") or {}
        if loc.get("country") != "tr":
            return None
        posting_id = str(item.get("id"))
        if not posting_id.isdigit():
            raise ValueError("bad posting id")
        return self._job(
            title=item.get("name"),
            url=f"https://jobs.smartrecruiters.com/{self.slug}/{posting_id}",
            location=loc.get("city"),
            posted_at=item.get("releasedDate"),
            labels=((item.get("typeOfEmployment") or {}).get("label"), (item.get("experienceLevel") or {}).get("label")),
        )


class WorkdayScraper(BaseScraper):
    # Workday'in resmi public API'si yok: kariyer sitesinin kendi kullandığı uç kullanılır (kullanıcı kararı)
    source = "workday"
    PAGE = 20  # Workday'in izin verdiği en büyük sayfa
    WD = re.compile(r"^wd[0-9]{1,2}$")
    SITE = re.compile(r"^[A-Za-z0-9_-]{1,50}$")

    def __init__(self, client: httpx.AsyncClient, slug: str, company: str, wd: str, site: str) -> None:
        super().__init__(client, slug, company)
        if not (self.WD.fullmatch(wd) and self.SITE.fullmatch(site)):
            raise ValueError(f"invalid workday config: {wd!r} {site!r}")
        self.host = f"{slug}.{wd}.myworkdayjobs.com"
        self.site = site
        self.allowed_hosts = frozenset({self.host})

    async def _items(self) -> list:
        items: list = []
        for page in range(MAX_PAGES):
            # "Turkey" araması ülke filtresi gibi çalışır (lokasyon metninde geçer); sonuç yine de aşağıda doğrulanır
            body = {"appliedFacets": {}, "limit": self.PAGE, "offset": page * self.PAGE, "searchText": "Turkey"}
            data = await self._json(f"https://{self.host}/wday/cxs/{self.slug}/{self.site}/jobs", body)
            batch = _expect(data, "jobPostings")
            items += batch
            if len(batch) < self.PAGE:
                break
        return items

    def _parse(self, item: dict) -> JobPosting | None:
        # ponytail: "2 Locations" gibi çok lokasyonlu ilanlar elenir; kaçan olursa detay ucu sorgulanır
        location = item.get("locationsText")
        path = item.get("externalPath")
        if not is_turkey(location) or not isinstance(path, str) or not path.startswith("/job/"):
            return None
        return self._job(title=item.get("title"), url=f"https://{self.host}/{self.site}{path}", location=location)


class AriTeknokentScraper(BaseScraper):
    """İTÜ ARI Teknokent kariyer portalı (HTML). robots.txt her şeye izin veriyor; API yok."""

    source = "ariteknokent"
    BASE = "https://kariyer.ariteknokent.com.tr"
    allowed_hosts = frozenset({"kariyer.ariteknokent.com.tr"})
    DELAY = 1.0  # robots'ta crawl-delay yok; yine de istekler arası nazik bekleme (saniye)
    # ponytail: portal eski ilanları kaldırmıyor (1 yıllık ilan görüldü); yaşa göre eleme
    MAX_AGE = timedelta(days=120)
    DATE = re.compile(r"Yayınlanma Tarihi:\s*(\d{2})/(\d{2})/(\d{4})")

    async def _items(self) -> list:
        cards, seen = [], set()
        for page in range(1, MAX_PAGES + 1):
            soup = BeautifulSoup(await self._fetch(f"{self.BASE}/search", page=str(page)), "html.parser")
            batch = [c for c in map(self._card, soup.select(".job-block-four .inner-box")) if c["url"] not in seen]
            if not batch:  # boş sayfa ya da son sayfanın tekrarı
                break
            seen.update(c["url"] for c in batch)
            cards += batch
            await asyncio.sleep(self.DELAY)

        items = []
        for card in cards:
            if not (is_internship(card["title"], card["type"]) or is_new_grad(card["title"])):
                continue  # yalnızca aday ilanların detay sayfası istenir
            if urlsplit(card["url"]).hostname not in self.allowed_hosts or not card["url"].startswith("https://"):
                log.warning("%s: skipped foreign link", self.source)  # SSRF: portal dışına istek atılmaz
                continue
            try:
                card |= self._detail(await self._fetch(card["url"]))
            except (httpx.HTTPError, ValueError) as e:
                log.warning("%s: detail failed (%s)", self.source, type(e).__name__)
                continue
            items.append(card)
            await asyncio.sleep(self.DELAY)
        return items

    @staticmethod
    def _text(el: Any) -> str | None:
        return el.get_text(" ", strip=True) if el else None

    def _card(self, box: Any) -> dict:
        link = box.select_one("h4 a")
        return {
            "title": self._text(link),
            "url": str(link.get("href", "")) if link else "",
            "type": self._text(box.select_one("li.time")),
            "location": self._text(box.select_one(".location")),
        }

    def _detail(self, html: bytes) -> dict:
        soup = BeautifulSoup(html, "html.parser")
        m = self.DATE.search(self._text(soup.select_one(".job-overview")) or "")
        posted = datetime(int(m[3]), int(m[2]), int(m[1]), tzinfo=timezone.utc) if m else None
        return {
            "company": self._text(soup.select_one(".company-widget .company-name")),
            "description": self._text(soup.select_one(".job-detail")),
            "posted_at": posted,
        }

    def _parse(self, item: dict) -> JobPosting | None:
        posted = item.get("posted_at")
        if posted is None or datetime.now(timezone.utc) - posted > self.MAX_AGE:
            return None
        return self._job(
            title=item["title"],
            url=item["url"],
            location=item["location"],
            posted_at=posted,
            labels=(item["type"],),
            description=item["description"],
            company=item["company"],
        )


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
