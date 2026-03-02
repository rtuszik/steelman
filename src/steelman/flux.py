from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class CurrentSource:
    source_kind: str
    source_url: str | None
    chart_name: str | None
    version: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sourceKind": self.source_kind,
            "sourceUrl": self.source_url,
            "chartName": self.chart_name,
            "version": self.version,
        }


@dataclass(slots=True)
class ChartIdentity:
    project: str | None
    vendor: str | None
    repo_url: str | None
    tokens: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "vendor": self.vendor,
            "repoUrl": self.repo_url,
            "tokens": self.tokens,
        }


@dataclass(slots=True)
class InventoryItem:
    release_name: str
    namespace: str
    cluster: str | None
    origin: str
    current: CurrentSource
    identity: ChartIdentity
    source_name: str | None = None
    source_namespace: str | None = None
    source_ref_kind: str | None = None
    source_ref_name: str | None = None
    source_ref_namespace: str | None = None
    chart_ref_kind: str | None = None
    chart_ref_name: str | None = None
    chart_ref_namespace: str | None = None
    inline_values: Any = None
    values_from_items: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    git_path: str | None = None

    def key(self) -> tuple[str | None, str, str]:
        return (self.cluster, self.namespace, self.release_name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "releaseName": self.release_name,
            "cluster": self.cluster,
            "namespace": self.namespace,
            "origin": self.origin,
            "current": self.current.to_dict(),
            "identity": self.identity.to_dict(),
            "sourceName": self.source_name,
            "sourceNamespace": self.source_namespace,
            "sourceRefKind": self.source_ref_kind,
            "sourceRefName": self.source_ref_name,
            "sourceRefNamespace": self.source_ref_namespace,
            "chartRefKind": self.chart_ref_kind,
            "chartRefName": self.chart_ref_name,
            "chartRefNamespace": self.chart_ref_namespace,
            "inlineValues": self.inline_values,
            "valuesFromItems": self.values_from_items,
            "notes": self.notes,
            "gitPath": self.git_path,
        }


@dataclass(slots=True)
class DhiCatalogItem:
    dhi_repo: str
    display_name: str
    description: str | None
    documentation_links: list[str]
    path: str
    last_seen_at: str | None = None

    def target_url(self) -> str:
        return f"oci://dhi.io/{self.dhi_repo}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "dhiRepo": self.dhi_repo,
            "displayName": self.display_name,
            "description": self.description,
            "documentationLinks": self.documentation_links,
            "path": self.path,
            "lastSeenAt": self.last_seen_at,
        }


@dataclass(slots=True)
class DhiImageCatalogItem:
    image_repo: str
    display_name: str
    description: str | None
    documentation_links: list[str]
    path: str
    last_seen_at: str | None = None

    def image_ref(self) -> str:
        return f"dhi.io/{self.image_repo}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "imageRepo": self.image_repo,
            "displayName": self.display_name,
            "description": self.description,
            "documentationLinks": self.documentation_links,
            "path": self.path,
            "lastSeenAt": self.last_seen_at,
        }


@dataclass(slots=True)
class ImageReference:
    path: str
    repository: str
    registry: str | None
    tag: str | None
    digest: str | None
    raw: str
    source: str

    def current_image(self) -> str:
        base = f"{self.registry}/{self.repository}" if self.registry else self.repository
        if self.digest:
            return f"{base}@{self.digest}"
        if self.tag:
            return f"{base}:{self.tag}"
        return base

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "repository": self.repository,
            "registry": self.registry,
            "tag": self.tag,
            "digest": self.digest,
            "raw": self.raw,
            "source": self.source,
        }


@dataclass(slots=True)
class ImageReplacement:
    path: str
    current_image: str
    current_repository: str
    current_tag: str | None
    dhi_image: str
    dhi_image_ref: str
    confidence: float
    reasons: list[str]
    evidence: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "currentImage": self.current_image,
            "currentRepository": self.current_repository,
            "currentTag": self.current_tag,
            "dhiImage": self.dhi_image,
            "dhiImageRef": self.dhi_image_ref,
            "confidence": round(self.confidence, 4),
            "reasons": self.reasons,
            "evidence": self.evidence,
        }


@dataclass(slots=True)
class MatchResult:
    release_name: str
    cluster: str | None
    namespace: str
    origin: str
    current: CurrentSource
    identity: ChartIdentity
    recommendation_type: str
    chart_replacement: CurrentSource | None
    image_replacements: list[ImageReplacement]
    chart_match_status: str
    chart_match_confidence: float
    chart_match_reasons: list[str]
    chart_match_evidence: list[str]
    reasons: list[str]
    evidence: list[str]
    analysis_notes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "releaseName": self.release_name,
            "cluster": self.cluster,
            "namespace": self.namespace,
            "origin": self.origin,
            "current": self.current.to_dict(),
            "identity": self.identity.to_dict(),
            "recommendationType": self.recommendation_type,
            "chartReplacement": (
                self.chart_replacement.to_dict() if self.chart_replacement else None
            ),
            "imageReplacements": [item.to_dict() for item in self.image_replacements],
            "chartMatchStatus": self.chart_match_status,
            "chartMatchConfidence": round(self.chart_match_confidence, 4),
            "chartMatchReasons": self.chart_match_reasons,
            "chartMatchEvidence": self.chart_match_evidence,
            "reasons": self.reasons,
            "evidence": self.evidence,
            "analysisNotes": self.analysis_notes,
            "notes": self.notes,
        }


@dataclass(slots=True)
class ScanError:
    source: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)
