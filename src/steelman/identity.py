from __future__ import annotations

import re
from urllib.parse import urlparse

from .flux import ChartIdentity, CurrentSource

TOKEN_RE = re.compile(r"[a-z0-9]+")
STOP_TOKENS = {
    "chart",
    "charts",
    "helm",
    "oci",
    "operator",
    "operators",
    "dashboard",
    "release",
    "collector",
    "distributed",
    "stack",
    "system",
    "default",
    "github",
    "ghcr",
    "io",
    "com",
    "www",
}


def normalize_name(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.lower().replace("_", "-").strip()
    normalized = normalized.removeprefix("oci://")
    if "/" in normalized:
        normalized = normalized.rsplit("/", 1)[-1]
    normalized = re.sub(r"(^helm-)|(-helm$)", "", normalized)
    normalized = re.sub(r"-chart$", "", normalized)
    normalized = re.sub(r"-+", "-", normalized)
    return normalized.strip("-")


def tokenize(*values: str | None) -> list[str]:
    tokens: set[str] = set()
    for value in values:
        if not value:
            continue
        normalized = value.lower().replace("_", "-")
        tokens.update(
            token
            for token in TOKEN_RE.findall(normalized)
            if token not in STOP_TOKENS and len(token) > 1
        )
    return sorted(tokens)


def extract_vendor_from_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    path_tokens = tokenize(parsed.path)
    host_tokens = tokenize(parsed.netloc)
    for token in path_tokens + host_tokens:
        if token not in STOP_TOKENS | {"index"}:
            return token
    return None


def build_identity(current: CurrentSource) -> ChartIdentity:
    project = normalize_name(current.chart_name)
    vendor = extract_vendor_from_url(current.source_url)
    repo_url = current.source_url
    tokens = tokenize(current.chart_name, current.source_url, project, vendor)
    return ChartIdentity(project=project, vendor=vendor, repo_url=repo_url, tokens=tokens)


def is_dhi_url(url: str | None) -> bool:
    if not url:
        return False
    return normalize_oci_host(url) == "dhi.io"


def normalize_oci_host(url: str) -> str | None:
    trimmed = url.removeprefix("oci://")
    candidate = f"https://{trimmed}" if "://" not in trimmed else trimmed
    parsed = urlparse(candidate)
    return parsed.netloc.lower() or None
