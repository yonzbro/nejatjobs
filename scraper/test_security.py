import asyncio
import json
import os

import httpx
import pytest
from pydantic import ValidationError

import database
import main
import scraper
from models import JobPosting, is_internship, is_long_term, is_new_grad, is_turkey
from scraper import (
    MAX_BYTES,
    AriTeknokentScraper,
    AshbyScraper,
    GreenhouseScraper,
    LeverScraper,
    SmartRecruitersScraper,
    WorkdayScraper,
    make_client,
)


def job(**kw):
    base = dict(source="lever", company="Acme", title="Stajyer", url="https://jobs.lever.co/acme/1")
    return JobPosting(**(base | kw))


def run_scraper(cls, handler, *args):
    async def go():
        async with make_client(httpx.MockTransport(handler)) as c:
            return await cls(c, "acme", "Acme", *args).fetch()
    return asyncio.run(go())


def run_lever(handler):
    return run_scraper(LeverScraper, handler)


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
    ("Smart Start Production Engineer", True),
    ("Ability to work 3-5 days a week", True),
    ("haftada en az 3 gün", True),
    ("Yaz Stajı", False),
    ("Summer Intern", False),
    ("16 months", False),
    ("7 days a week support", False),
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


@pytest.mark.parametrize("text,expected", [
    ("Software Engineer (New Grad)", True),
    ("Management Trainee for People & Culture (Fresh Grad)", True),
    ("Growth Manager - New Grad", True),
    ("Yeni Mezun Aday Mühendis", True),
    ("Graduate Program 2027", True),
    ("Senior Software Engineer", False),
    ("Postgraduate Researcher", False),
])
def test_new_grad_detection(text, expected):
    assert is_new_grad(text) is expected


@pytest.mark.parametrize("text,expected", [
    ("İstanbul", True),
    ("ISTANBUL, TR", True),
    ("Bursa, , Turkey", True),
    ("Türkiye", True),
    ("Turkiye - Remote", True),
    ("Istanbul, Turkey; London", True),
    ("Lisboa", False),
    ("Turkmenistan", False),
    (None, False),
])
def test_turkey_detection(text, expected):
    assert is_turkey(text) is expected

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


# --- Greenhouse / Ashby / SmartRecruiters / Workday ---

def test_greenhouse_filters_country_kind_and_host():
    gh = lambda title, loc, url: {"title": title, "location": {"name": loc}, "absolute_url": url}
    ok = "https://job-boards.greenhouse.io/acme/jobs/1"
    items = [
        gh("Software Engineer - New Grad", "Istanbul, Turkey", ok),
        gh("Intern", "London", ok),                                         # TR değil
        gh("Senior Engineer", "Istanbul", ok),                              # staj / mezun değil
        gh("Intern", "Istanbul", "https://evil.com/phish"),                 # yabancı host
        gh("Intern", "Istanbul", "javascript:alert(1)"),
    ]
    jobs = run_scraper(GreenhouseScraper, lambda req: httpx.Response(200, json={"jobs": items}))
    assert [(j.title, j.is_new_grad) for j in jobs] == [("Software Engineer - New Grad", True)]


def test_ashby_uses_employment_type_and_skips_unlisted():
    base = {
        "title": "People Team", "employmentType": "Intern", "isListed": True, "location": "Istanbul",
        "address": {"postalAddress": {"addressCountry": "Turkey"}},
        "jobUrl": "https://jobs.ashbyhq.com/acme/1", "descriptionPlain": "Ability to work 3 days a week",
    }
    items = [base, base | {"isListed": False}, base | {"address": None, "location": "Paris"}]
    jobs = run_scraper(AshbyScraper, lambda req: httpx.Response(200, json={"jobs": items}))
    assert len(jobs) == 1 and jobs[0].is_long_term and not jobs[0].is_new_grad


SR_ITEM = {
    "id": "744000153116813", "name": "Smart Start BPS Method Engineer",
    "location": {"country": "tr", "city": "Bursa"}, "releasedDate": "2026-10-02T08:08:58.066Z",
    "experienceLevel": {"id": "internship", "label": "Internship"},
}


def test_smartrecruiters_builds_url_from_numeric_id_only():
    items = [SR_ITEM, SR_ITEM | {"id": "../../evil"}, SR_ITEM | {"location": {"country": "de"}}]
    jobs = run_scraper(SmartRecruitersScraper, lambda req: httpx.Response(200, json={"content": items}))
    assert [str(j.url) for j in jobs] == ["https://jobs.smartrecruiters.com/acme/744000153116813"]
    assert jobs[0].is_long_term   # başlıkta "intern" yok; staj bilgisi experienceLevel'dan gelir


def test_smartrecruiters_paginates_with_cap(monkeypatch):
    monkeypatch.setattr(scraper, "MAX_PAGES", 3)
    offsets = []

    def handler(req):
        offsets.append(req.url.params["offset"])
        assert req.url.params["country"] == "tr"
        return httpx.Response(200, json={"content": [SR_ITEM] * SmartRecruitersScraper.PAGE})  # hep dolu sayfa

    run_scraper(SmartRecruitersScraper, handler)
    assert offsets == ["0", "100", "200"]   # sonsuz döngü yok


def test_workday_posts_search_and_validates_path():
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, json={"jobPostings": [
            {"title": "Management Trainee", "locationsText": "Istanbul", "externalPath": "/job/Istanbul/MT_1"},
            {"title": "Intern", "locationsText": "Istanbul", "externalPath": "//evil.com/x"},
            {"title": "Intern", "locationsText": "2 Locations", "externalPath": "/job/x/Intern_2"},
        ]})

    jobs = run_scraper(WorkdayScraper, handler, "wd3", "Careers")
    req = seen[0]
    assert req.method == "POST" and req.url.host == "acme.wd3.myworkdayjobs.com"
    assert json.loads(req.content)["searchText"] == "Turkey"
    assert [str(j.url) for j in jobs] == ["https://acme.wd3.myworkdayjobs.com/Careers/job/Istanbul/MT_1"]


ARI = "https://kariyer.ariteknokent.com.tr"


def ari_card(title, href, kind="Internship"):
    return (f'<div class="job-block-four"><div class="inner-box"><ul><li class="time">{kind}</li></ul>'
            f'<h4><a href="{href}">{title}</a></h4><div class="location">İTÜ Teknokent</div></div></div>')


def ari_detail(company, date):
    return (f'<ul class="job-overview"><li>Yayınlanma Tarihi: {date}</li></ul>'
            f'<div class="job-detail">Haftada 3 gün</div>'
            f'<div class="company-widget"><h5 class="company-name">{company}</h5></div>').encode()


def test_ariteknokent_parses_filters_and_never_fetches_foreign_links(monkeypatch):
    monkeypatch.setattr(AriTeknokentScraper, "DELAY", 0)
    today = __import__("datetime").date.today().strftime("%d/%m/%Y")
    page1 = "".join([
        ari_card("Stajyer &lt;script&gt;x&lt;/script&gt;", f"{ARI}/ilan/1"),
        ari_card("Senior Developer", f"{ARI}/ilan/2", "Full Time"),       # staj değil → detay istenmez
        ari_card("Stajyer", "https://169.254.169.254/latest"),            # portal dışı → asla istenmez
        ari_card("Stajyer", f"{ARI}/ilan/3"),                             # eski ilan → elenir
    ])
    requested = []

    def handler(req):
        requested.append(str(req.url))
        if req.url.path == "/search":
            return httpx.Response(200, text=page1)  # her sayfa aynı: son sayfanın tekrarı gibi
        if req.url.path == "/ilan/1":
            return httpx.Response(200, content=ari_detail("Acme <b>A.Ş.</b>", today))
        return httpx.Response(200, content=ari_detail("Eski", "01/01/2020"))

    jobs = run_scraper(AriTeknokentScraper, handler)
    assert [(j.title, j.company) for j in jobs] == [("Stajyer <script>x</script>", "Acme A.Ş.")]
    assert jobs[0].is_long_term
    assert not any("169.254" in u or "/ilan/2" in u for u in requested)
    assert sum("/search" in u for u in requested) == 2   # tekrar eden sayfada durur


@pytest.mark.parametrize("wd,site", [("wd3.evil.com", "Careers"), ("wd3", "../admin"), ("wd3", "a/b"), ("x", "C")])
def test_workday_rejects_bad_config(wd, site):
    with pytest.raises(ValueError):
        WorkdayScraper(None, "acme", "Acme", wd, site)


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


# --- Retry / backoff ---

def test_retries_transient_errors(monkeypatch):
    monkeypatch.setattr(scraper, "RETRY_DELAY", 0)
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json=[GOOD])

    assert len(run_lever(handler)) == 1
    assert len(calls) == 3


def test_does_not_retry_client_errors(monkeypatch):
    monkeypatch.setattr(scraper, "RETRY_DELAY", 0)
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(404)

    with pytest.raises(httpx.HTTPStatusError):
        run_lever(handler)
    assert len(calls) == 1


# --- Telegram ---

def test_telegram_message_is_plain_text_and_chunked():
    evil = job(title="<b>x</b> [tıkla](https://evil.com)", is_long_term=True)
    msgs = main.format_messages([evil] + [job(url=f"https://jobs.lever.co/acme/{i}") for i in range(200)])
    assert "<b>x</b> [tıkla](https://evil.com)" in msgs[0]   # olduğu gibi, yorumlanmadan
    assert msgs[0].startswith("🔥 UZUN DÖNEM")
    assert len(msgs) > 1 and all(len(m) <= main.TELEGRAM_LIMIT for m in msgs)


def test_telegram_error_does_not_leak_token(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:SECRET")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "@test")
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(401)

    async def go():
        async with make_client(httpx.MockTransport(handler)) as c:
            await main.notify(c, [job()])

    with pytest.raises(RuntimeError) as e:
        asyncio.run(go())
    assert "SECRET" not in str(e.value)
    assert "parse_mode" not in seen["body"]
