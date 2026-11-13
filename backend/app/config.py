from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "news.db"


def _load_dotenv(path: Path) -> None:
    """Read KEY=VALUE lines from the project-root .env into os.environ.
    Real environment variables win over the file."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")


def unsplash_key() -> str | None:
    return os.environ.get("UNSPLASH_ACCESS_KEY") or None


def db_path() -> Path:
    """NEWS_DB_PATH overrides the database location (tests use a temp file)."""
    return Path(os.environ.get("NEWS_DB_PATH", DB_PATH))


def _load(name: str) -> dict:
    return yaml.safe_load((CONFIG_DIR / name).read_text())


@lru_cache
def feeds() -> list[dict]:
    return _load("feeds.yaml")["feeds"]


@lru_cache
def taxonomy() -> dict:
    return _load("taxonomy.yaml")


@lru_cache
def scoring() -> dict:
    return _load("scoring.yaml")


@lru_cache
def images() -> dict:
    return _load("images.yaml")


def publishers() -> dict[str, dict]:
    """Distinct publishers keyed by name. A publisher listed under several feeds
    takes the best (lowest) tier and the union of topics."""
    out: dict[str, dict] = {}
    for f in feeds():
        p = out.setdefault(f["name"], {"name": f["name"], "tier": f["tier"], "topics": set()})
        p["tier"] = min(p["tier"], f["tier"])
        p["topics"].update(f["topics"])
    return out


def domain_map() -> dict[str, str]:
    return {d: f["name"] for f in feeds() for d in f.get("domains", [])}


def tier1_list(topic: str) -> set[str]:
    return {n for n, p in publishers().items() if p["tier"] == 1 and topic in p["topics"]}
