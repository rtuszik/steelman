from __future__ import annotations

import io
import tarfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

import httpx
import yaml

from .cache import default_cache_dir, load_json, write_json
from .flux import DhiCatalogItem, DhiImageCatalogItem

ARCHIVE_URL = "https://codeload.github.com/docker-hardened-images/catalog/tar.gz/refs/heads/main"
CACHE_FILE = "catalog.json"


@dataclass(slots=True)
class CatalogSnapshot:
    charts: list[DhiCatalogItem]
    images: list[DhiImageCatalogItem]
    fetched_at: str
    source: str
    degraded: bool = False
    notes: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "fetchedAt": self.fetched_at,
            "source": self.source,
            "degraded": self.degraded,
            "notes": self.notes or [],
            "charts": [item.to_dict() for item in self.charts],
            "images": [item.to_dict() for item in self.images],
        }


def cache_path() -> Path:
    return default_cache_dir() / CACHE_FILE


def fetch_catalog(offline: bool = False, max_age_hours: int = 24) -> CatalogSnapshot:
    cached = _load_cached_snapshot()
    if offline:
        if cached is None:
            raise RuntimeError("offline mode requested but no cached catalog is available")
        cached.degraded = True
        cached.notes = (cached.notes or []) + ["Using cached catalog in offline mode"]
        return cached

    if cached and _is_fresh(cached.fetched_at, max_age_hours):
        return cached

    try:
        archive = _download_catalog_archive()
        snapshot = parse_catalog_archive(archive)
        write_json(cache_path(), snapshot.to_dict())
        return snapshot
    except Exception as exc:  # pragma: no cover
        if cached is None:
            raise
        cached.degraded = True
        cached.notes = (cached.notes or []) + [f"Catalog refresh failed: {exc}"]
        return cached


def parse_catalog_archive(content: bytes) -> CatalogSnapshot:
    fetched_at = datetime.now(tz=UTC).isoformat()
    chart_docs, chart_overviews = _extract_section(content, "chart")
    image_docs, image_overviews = _extract_section(content, "image")
    charts = [
        _build_chart_item(name, chart_docs.get(name, {}), chart_overviews.get(name), fetched_at)
        for name in sorted(set(chart_docs) | set(chart_overviews))
    ]
    images = [
        _build_image_item(name, image_docs.get(name, {}), image_overviews.get(name), fetched_at)
        for name in sorted(set(image_docs) | set(image_overviews))
    ]
    return CatalogSnapshot(
        charts=charts,
        images=images,
        fetched_at=fetched_at,
        source="github-archive",
    )


def _extract_section(
    content: bytes,
    section: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    info_docs: dict[str, dict[str, Any]] = {}
    overviews: dict[str, str] = {}
    with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            path = PurePosixPath(member.name)
            if len(path.parts) < 4 or path.parts[1] != section:
                continue
            repo_name = path.parts[2]
            handle = archive.extractfile(member)
            if handle is None:
                continue
            try:
                if path.name == "info.yaml":
                    parsed = yaml.safe_load(handle.read().decode("utf-8")) or {}
                    if isinstance(parsed, dict):
                        info_docs[repo_name] = parsed
                elif path.name == "overview.md":
                    overviews[repo_name] = handle.read().decode("utf-8").strip()
            finally:
                handle.close()
    return info_docs, overviews


def _download_catalog_archive() -> bytes:
    with httpx.Client(follow_redirects=True, timeout=30.0) as client:
        response = client.get(ARCHIVE_URL, headers={"User-Agent": "steelman/0.1.0"})
        response.raise_for_status()
        return response.content


def _build_chart_item(
    repo_name: str,
    info: dict[str, Any],
    overview: str | None,
    fetched_at: str,
) -> DhiCatalogItem:
    return DhiCatalogItem(
        dhi_repo=repo_name,
        display_name=_display_name(info, repo_name),
        description=_description(info, overview),
        documentation_links=_collect_links(info),
        path=f"chart/{repo_name}",
        last_seen_at=fetched_at,
    )


def _build_image_item(
    repo_name: str,
    info: dict[str, Any],
    overview: str | None,
    fetched_at: str,
) -> DhiImageCatalogItem:
    image_repo = _first_str(info, "image", "imageRepo", "repository", "name") or repo_name
    return DhiImageCatalogItem(
        image_repo=image_repo,
        display_name=_display_name(info, repo_name),
        description=_description(info, overview),
        documentation_links=_collect_links(info),
        path=f"image/{repo_name}",
        last_seen_at=fetched_at,
    )


def _display_name(info: dict[str, Any], repo_name: str) -> str:
    return (
        _first_str(info, "displayName", "display_name", "name", "title")
        or repo_name.replace("-", " ").title()
    )


def _description(info: dict[str, Any], overview: str | None) -> str | None:
    description = _first_str(info, "description", "summary") or _first_str_nested(
        info, ("chart", "description"), ("metadata", "description")
    )
    if not description and overview:
        return overview.splitlines()[0].lstrip("# ").strip()
    return description


def _collect_links(info: dict[str, Any]) -> list[str]:
    links: list[str] = []
    candidates: list[Any] = [
        info.get("documentation"),
        info.get("docs"),
        info.get("links"),
        info.get("urls"),
        info.get("homepage"),
        info.get("home"),
    ]
    nested = _first_value_nested(
        info,
        ("chart", "home"),
        ("chart", "sources"),
        ("metadata", "home"),
        ("metadata", "sources"),
    )
    if nested is not None:
        candidates.append(nested)
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.startswith("http"):
            links.append(candidate)
        elif isinstance(candidate, list):
            links.extend(
                item for item in candidate if isinstance(item, str) and item.startswith("http")
            )
        elif isinstance(candidate, dict):
            links.extend(
                item
                for item in candidate.values()
                if isinstance(item, str) and item.startswith("http")
            )
    return sorted(set(links))


def _first_str(info: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = info.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _first_value_nested(info: dict[str, Any], *paths: tuple[str, ...]) -> Any:
    for path in paths:
        current: Any = info
        for step in path:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(step)
        if current:
            return current
    return None


def _first_str_nested(info: dict[str, Any], *paths: tuple[str, ...]) -> str | None:
    value = _first_value_nested(info, *paths)
    if isinstance(value, str):
        return value.strip()
    return None


def _load_cached_snapshot() -> CatalogSnapshot | None:
    payload = load_json(cache_path())
    if payload is None:
        return None
    if "charts" not in payload or "images" not in payload:
        return None
    charts = [DhiCatalogItem(**_from_json_chart(item)) for item in payload.get("charts", [])]
    images = [DhiImageCatalogItem(**_from_json_image(item)) for item in payload.get("images", [])]
    return CatalogSnapshot(
        charts=charts,
        images=images,
        fetched_at=str(payload["fetchedAt"]),
        source=str(payload.get("source", "cache")),
        degraded=bool(payload.get("degraded", False)),
        notes=list(payload.get("notes", [])),
    )


def _from_json_chart(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "dhi_repo": item["dhiRepo"],
        "display_name": item["displayName"],
        "description": item.get("description"),
        "documentation_links": item.get("documentationLinks", []),
        "path": item["path"],
        "last_seen_at": item.get("lastSeenAt"),
    }


def _from_json_image(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "image_repo": item["imageRepo"],
        "display_name": item["displayName"],
        "description": item.get("description"),
        "documentation_links": item.get("documentationLinks", []),
        "path": item["path"],
        "last_seen_at": item.get("lastSeenAt"),
    }


def _is_fresh(timestamp: str, max_age_hours: int) -> bool:
    fetched_at = datetime.fromisoformat(timestamp)
    return datetime.now(tz=UTC) - fetched_at < timedelta(hours=max_age_hours)
