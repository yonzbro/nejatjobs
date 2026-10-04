"""Veri modeli. Dış kaynaktan gelen her alan güvenilmezdir (untrusted data)."""
import hashlib
import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, computed_field, field_validator

# Görünmez karakterler: kontrol karakterleri, zero-width ve bidi override (metni ters gösterip kandırma)
_INVISIBLE = re.compile(r"[\x00-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩]")
_WHITESPACE = re.compile(r"\s+")

INTERNSHIP = re.compile(r"\bintern(?:ship)?s?\b|\bstaj|\btrainee", re.IGNORECASE)
NEW_GRAD = re.compile(
    r"\b(?:new|fresh|recent)[\s-]*grad|\bgraduate\s+(?:program|programme|trainee)|management\s+trainee"
    r"|yeni\s+mezun|aday\s+m[üu]hendis",
    re.IGNORECASE,
)
# ponytail: anahtar kelime heuristic'i; kaçan kalıp görülünce buraya eklenir
LONG_TERM = re.compile(
    r"uzun\s*d[öo]nem|long[\s-]*term|\b(?:6|9|12)[\s-]*(?:ay|months?)\b"
    r"|part[\s-]*time|yar[ıi]\s*zamanl[ıi]|\bftc\b"
    r"|smart\s+start"  # Bosch: okul döneminde haftada 3-5 gün çalışan öğrenci programı
    r"|\b[2-5](?:\s*-\s*[2-5])?\s*days?\s*(?:a|per)\s*week|haftada\s*(?:en\s*az\s*)?[2-5]",
    re.IGNORECASE,
)
TURKEY = re.compile(
    r"\b(?:turkey|t[üu]rkiye|istanbul|ankara|izmir|bursa|kocaeli|gebze|antalya|manisa|eski[şs]ehir)\b",
    re.IGNORECASE,
)


def _any(pattern: re.Pattern[str], texts: tuple[str | None, ...]) -> bool:
    return any(isinstance(t, str) and pattern.search(t) for t in texts)


def is_internship(*texts: str | None) -> bool:
    return _any(INTERNSHIP, texts)


def is_new_grad(*texts: str | None) -> bool:
    return _any(NEW_GRAD, texts)


def is_long_term(*texts: str | None) -> bool:
    return _any(LONG_TERM, texts)


def is_turkey(*texts: str | None) -> bool:
    return _any(TURKEY, texts)


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
    is_new_grad: bool = False

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
