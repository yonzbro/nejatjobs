import asyncio
import json
import os

import httpx
import pytest
from pydantic import ValidationError

import database
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


# --- Veritabanı yazma ---

def run_upsert(handler, jobs):
    async def go():
        async with make_client(httpx.MockTransport(handler)) as c:
            return await database.upsert_jobs(c, jobs)
    return asyncio.run(go())


@pytest.fixture
def supabase_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_test")


def test_upsert_sends_json_params_and_dedups(supabase_env):
    seen = {}

    def handler(req):
        seen["req"] = req
        return httpx.Response(200, json=[{"new_hash": job().dedup_hash}])

    evil = "x'); drop table jobs; --"
    new = run_upsert(handler, [job(), job(title="Stajyer"), job(title=evil, url="https://jobs.lever.co/acme/2")])
    req = seen["req"]
    payload = json.loads(req.content)["payload"]
    assert req.url.path == "/rest/v1/rpc/upsert_jobs"
    assert len(payload) == 2                       # aynı hash tek gönderilir
    assert payload[1]["title"] == evil             # SQL değil, düz JSON veri
    assert req.headers["apikey"] == "sb_secret_test"
    assert "authorization" not in req.headers      # secret key Bearer'a konmaz
    assert new == {job().dedup_hash}


def test_upsert_skips_network_when_empty(supabase_env):
    assert run_upsert(lambda req: pytest.fail("no request expected"), []) == set()


def test_upsert_refuses_plain_http(monkeypatch, supabase_env):
    monkeypatch.setenv("SUPABASE_URL", "http://test.supabase.co")
    with pytest.raises(ValueError):
        run_upsert(lambda req: httpx.Response(200, json=[]), [job()])


def test_upsert_raises_on_auth_error(supabase_env):
    with pytest.raises(httpx.HTTPStatusError):
        run_upsert(lambda req: httpx.Response(401, json={"message": "Invalid API key"}), [job()])


# --- RLS: gerçek Supabase'e saldırgan gözüyle (yalnızca publishable/anon key) ---
# Anahtarlar ortamda yoksa atlanır. RLS sağlamsa hiçbir şey yazılmaz.

needs_supabase = pytest.mark.skipif(
    not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_PUBLISHABLE_KEY")),
    reason="SUPABASE_URL / SUPABASE_PUBLISHABLE_KEY ayarlı değil",
)
PROBE = "0" * 64  # var olmayan test satırı: açık olsa bile gerçek veriye dokunulmaz
PROBE_ROW = {"dedup_hash": PROBE, "source": "test", "company": "x", "title": "x", "url": "https://x.test"}
DENIED = {401, 403, 404}


@pytest.fixture
def anon():
    base = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1"
    with httpx.Client(base_url=base, headers={"apikey": os.environ["SUPABASE_PUBLISHABLE_KEY"]}, timeout=15) as c:
        yield c


@needs_supabase
def test_anon_can_read(anon):
    assert anon.get("/jobs", params={"select": "dedup_hash", "limit": 1}).status_code == 200


@needs_supabase
@pytest.mark.parametrize("method,path,kw", [
    ("POST", "/jobs", {"json": PROBE_ROW}),
    ("PATCH", "/jobs", {"params": {"dedup_hash": f"eq.{PROBE}"}, "json": {"title": "hacked"}}),
    ("DELETE", "/jobs", {"params": {"dedup_hash": f"eq.{PROBE}"}}),
    ("POST", "/rpc/upsert_jobs", {"json": {"payload": [PROBE_ROW]}}),
])
def test_anon_cannot_write(anon, method, path, kw):
    # PATCH/DELETE için 204 = yetki revoke edilmemiş (yalnızca RLS koruyor) → ikinci kilit eksik
    r = anon.request(method, path, **kw)
    assert r.status_code in DENIED, f"RLS AÇIĞI: anon {method} {path} → {r.status_code}"


@needs_supabase
def test_request_without_key_rejected():
    r = httpx.get(os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/jobs", timeout=15)
    assert r.status_code == 401
