"""Supabase'e yazma. SQL string'i kurulmaz: veri JSON parametre olarak RPC fonksiyonuna gider."""
import os

import httpx

from models import JobPosting


def _config() -> tuple[str, str]:
    url = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SECRET_KEY"]
    if not url.startswith("https://"):
        raise ValueError("SUPABASE_URL must be https")
    return url, key


async def upsert_jobs(client: httpx.AsyncClient, jobs: list[JobPosting]) -> set[str]:
    """İlanları yazar; ilk kez görülenlerin dedup_hash'lerini döner."""
    if not jobs:
        return set()
    url, key = _config()
    # Aynı satır tek INSERT'te iki kez güncellenemez (Postgres hatası) → önce tekilleştir
    unique = {j.dedup_hash: j for j in jobs}
    r = await client.post(
        f"{url}/rest/v1/rpc/upsert_jobs",
        json={"payload": [j.model_dump(mode="json") for j in unique.values()]},
        headers={"apikey": key},  # sb_secret_ anahtarı JWT değildir, Bearer'a konmaz
    )
    r.raise_for_status()
    return {row["new_hash"] for row in r.json()}
