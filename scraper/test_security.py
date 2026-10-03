import asyncio

import httpx
import pytest
from pydantic import ValidationError

from models import JobPosting, is_internship, is_long_term
from scraper import MAX_BYTES, LeverScraper, make_client


def job(**kw):
    base = dict(source="lever", company="Acme", title="Stajyer", url="https://jobs.lever.co/acme/1")
    return JobPosting(**(base | kw))


def run_lever(handler):
    async def go():
        async with make_client(httpx.MockTransport(handler)) as c:
            return await LeverScraper(c, "acme", "Acme").fetch()
    return asyncio.run(go())


# --- Model: URL ---

@pytest.mark.parametrize("url", [
    "javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "http://jobs.lever.co/acme/1",       # https değil
    "https://user:pass@evil.com/",       # kimlik bilgisi gömülü
    "ftp://evil.com/a",
    "//evil.com",
])
def test_rejects_dangerous_urls(url):
    with pytest.raises(ValidationError):
        job(url=url)


# --- Model: metin ---

def test_strips_invisible_and_bidi_chars():
    assert job(title="Staj‮yer\x00\n  İlanı").title == "Stajyer İlanı"


def test_html_kept_as_plain_text():
    # Saklama anında escape yok; React render ederken escape eder
    assert job(title="<script>x</script>").title == "<script>x</script>"


def test_rejects_oversized_empty_and_extra_fields():
    with pytest.raises(ValidationError):
        job(title="a" * 301)
    with pytest.raises(ValidationError):
        job(title="\x00​")      # temizlenince boş kalır
    with pytest.raises(ValidationError):
        job(is_admin=True)           # extra="forbid"


def test_dedup_hash_depends_on_source_and_url_only():
    assert job().dedup_hash == job(title="Başka").dedup_hash
    assert job().dedup_hash != job(url="https://jobs.lever.co/acme/2").dedup_hash


# --- Sınıflandırma ---

@pytest.mark.parametrize("text,expected", [
    ("Uzun Dönem Stajyer", True),
    ("UZUN DÖNEM STAJ", True),
    ("Long-term Intern", True),
    ("Intern (6 months FTC)", True),
    ("6-month Internship", True),
    ("6 Ay Stajyer", True),
    ("Part-time Intern", True),
    ("YARI ZAMANLI STAJYER", True),
    ("Yaz Stajı", False),
    ("Summer Intern", False),
    ("16 months", False),
])
def test_long_term_detection(text, expected):
    assert is_long_term(text) is expected


@pytest.mark.parametrize("text,expected", [
    ("Stajyer", True),
    ("Software Engineering Intern", True),
    ("Internship", True),
    ("Internal Audit Specialist", False),
])
def test_internship_detection(text, expected):
    assert is_internship(text) is expected


# --- Scraper ---

GOOD = {
    "text": "Stajyer (Uzun Dönem)",
    "hostedUrl": "https://jobs.lever.co/acme/1",
    "country": "TR",
    "categories": {"commitment": "Internship", "location": "İstanbul"},
    "createdAt": 1786020608551,
}


def test_lever_filters_and_skips_malicious_items():
    items = [
        GOOD,
        GOOD | {"country": "RO"},
        GOOD | {"text": "Backend Engineer", "categories": {"commitment": "Full-time"}},
        GOOD | {"hostedUrl": "javascript:alert(1)"},
        GOOD | {"hostedUrl": "https://evil.com/phish"},   # Lever dışı host
        "not a dict",
        None,
    ]
    jobs = run_lever(lambda req: httpx.Response(200, json=items))
    assert [j.title for j in jobs] == ["Stajyer (Uzun Dönem)"]
    assert jobs[0].is_long_term
    assert jobs[0].posted_at.year == 2026


def test_lever_rejects_oversized_response():
    big = b"[" + b" " * (MAX_BYTES + 1) + b"]"
    with pytest.raises(ValueError):
        run_lever(lambda req: httpx.Response(200, content=big))


def test_lever_does_not_follow_redirects():
    redirect = httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data/"})
    with pytest.raises(httpx.HTTPStatusError):
        run_lever(lambda req: redirect)


@pytest.mark.parametrize("slug", ["../admin", "acme?x=1", "ACME", "", "a/b"])
def test_rejects_bad_slugs(slug):
    with pytest.raises(ValueError):
        LeverScraper(None, slug, "X")
