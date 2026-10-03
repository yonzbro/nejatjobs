"""Veri modeli. Dış kaynaktan gelen her alan güvenilmezdir (untrusted data)."""
import hashlib
import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, computed_field, field_validator

# Görünmez karakterler: kontrol karakterleri, zero-width ve bidi override (metni ters gösterip kandırma)
_INVISIBLE = re.compile(r"[\x00-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩]")
_WHITESPACE = re.compile(r"\s+")

INTERNSHIP = re.compile(r"\bintern(?:ship)?s?\b|\bstaj|\btrainee", re.IGNORECASE)
# ponytail: anahtar kelime heuristic'i; kaçan kalıp görülünce buraya eklenir
LONG_TERM = re.compile(
    r"uzun\s*d[öo]nem|long[\s-]*term|\b(?:6|9|12)[\s-]*(?:ay|months?)\b"
    r"|part[\s-]*time|yar[ıi]\s*zamanl[ıi]|\bftc\b",
    re.IGNORECASE,
)


def is_internship(*texts: str | None) -> bool:
    return any(t and INTERNSHIP.search(t) for t in texts)


def is_long_term(*texts: str | None) -> bool:
    return any(t and LONG_TERM.search(t) for t in texts)


class JobPosting(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str = Field(pattern=r"^[a-z]+$", max_length=20)
    company: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=300)
    url: HttpUrl
    location: str | None = Field(default=None, max_length=200)
    country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    posted_at: datetime | None = None
    is_long_term: bool = False

    @field_validator("company", "title", "location", mode="before")
    @classmethod
    def clean_text(cls, v: object) -> object:
        # HTML escape burada yapılmaz: escape, render anında (React) yapılır
        if isinstance(v, str):
            return _INVISIBLE.sub("", _WHITESPACE.sub(" ", v)).strip()
        return v

    @field_validator("url")
    @classmethod
    def safe_url(cls, v: HttpUrl) -> HttpUrl:
        if v.scheme != "https":
            raise ValueError("only https URLs are allowed")
        if v.username or v.password:
            raise ValueError("URL must not contain credentials")
        return v

    @computed_field
    @property
    def dedup_hash(self) -> str:
        return hashlib.sha256(f"{self.source}|{self.url}".encode()).hexdigest()
