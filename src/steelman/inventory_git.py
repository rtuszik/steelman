from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from .flux import CurrentSource, InventoryItem, ScanError
from .identity import build_identity

SOURCE_KINDS = {
    "HelmRepository": "helm",
    "OCIRepository": "oci",
}


def scan_repo(repo_path: Path) -> tuple[list[InventoryItem], list[ScanError]]:
    items: list[InventoryItem] = []
    errors: list[ScanError] = []
    documents: list[tuple[dict[str, Any], Path]] = []
    for path in sorted(repo_path.rglob("*")):
        if path.is_dir():
            continue
        if path.suffix not in {".yaml", ".yml"}:
            continue
        try:
            for document in yaml.safe_load_all(path.read_text(encoding="utf-8")):
                if isinstance(document, dict):
                    documents.append((document, path))
        except Exception as exc:
            errors.append(ScanError(source=str(path), message=f"Failed to parse YAML: {exc}"))

    source_index = _build_source_index(documents)
    for document, path in documents:
        if document.get("kind") != "HelmRelease":
            continue
        items.append(_helm_release_to_item(document, path, source_index))
    return items, errors


def _build_source_index(
    documents: Iterable[tuple[dict[str, Any], Path]],
) -> dict[tuple[str, str, str], dict[str, Any]]:
    index: dict[tuple[str, str, str], dict[str, Any]] = {}
    for document, _ in documents:
        kind = document.get("kind")
        if kind not in SOURCE_KINDS:
            continue
        metadata = document.get("metadata") or {}
        name = metadata.get("name")
        namespace = metadata.get("namespace", "default")
        if name:
            index[(kind, namespace, name)] = document
    return index


def _helm_release_to_item(
    document: dict[str, Any],
    path: Path,
    source_index: dict[tuple[str, str, str], dict[str, Any]],
) -> InventoryItem:
    metadata = document.get("metadata") or {}
    spec = document.get("spec") or {}
    namespace = metadata.get("namespace", "default")
    release_name = metadata.get("name", "unknown")
    chart_spec = ((spec.get("chart") or {}).get("spec")) or {}
    chart_ref = spec.get("chartRef") or {}
    source_ref = chart_spec.get("sourceRef") or {}

    source_kind = "unknown"
    source_url = None
    chart_name = chart_spec.get("chart")
    version = chart_spec.get("version")
    source_name = None
    source_namespace = namespace
    source_ref_kind = None
    source_ref_name = None
    source_ref_namespace = None
    chart_ref_kind = None
    chart_ref_name = None
    chart_ref_namespace = None
    notes: list[str] = []
    inline_values = spec.get("values")
    values_from_items = spec.get("valuesFrom") or []

    if chart_spec:
        source_ref_kind = _string_or_none(source_ref.get("kind"))
        source_ref_name = _string_or_none(source_ref.get("name"))
        source_ref_namespace = _string_or_default(source_ref.get("namespace"), namespace)
        source_namespace = source_ref_namespace
        source_name = source_ref_name
        source_doc = None
        if source_ref_kind and source_ref_name:
            source_doc = source_index.get(
                (source_ref_kind, source_ref_namespace, source_ref_name)
            )
        source_kind = SOURCE_KINDS.get(source_ref_kind, "unknown")
        source_url = _extract_source_url(source_doc)
        if source_doc is None and source_ref_name:
            notes.append(f"Missing referenced source {source_ref_kind}/{source_ref_name}")
    elif chart_ref:
        chart_ref_kind = _string_or_none(chart_ref.get("kind"))
        chart_ref_name = _string_or_none(chart_ref.get("name"))
        chart_ref_namespace = _string_or_default(chart_ref.get("namespace"), namespace)
        source_name = chart_ref_name
        source_namespace = chart_ref_namespace
        source_kind = SOURCE_KINDS.get(chart_ref_kind, "unknown")
        source_doc = None
        if chart_ref_kind and chart_ref_name:
            source_doc = source_index.get((chart_ref_kind, chart_ref_namespace, chart_ref_name))
        source_url = _extract_source_url(source_doc)
        chart_name = chart_name or chart_ref_name
        if source_doc is None and chart_ref_name:
            notes.append(f"Missing referenced source {chart_ref_kind}/{chart_ref_name}")
    else:
        notes.append("HelmRelease is missing spec.chart.spec and spec.chartRef")

    current = CurrentSource(
        source_kind=source_kind,
        source_url=source_url,
        chart_name=chart_name,
        version=version,
    )
    return InventoryItem(
        release_name=release_name,
        namespace=namespace,
        cluster=None,
        origin="git",
        current=current,
        identity=build_identity(current),
        source_name=source_name,
        source_namespace=source_namespace,
        source_ref_kind=source_ref_kind,
        source_ref_name=source_ref_name,
        source_ref_namespace=source_ref_namespace,
        chart_ref_kind=chart_ref_kind,
        chart_ref_name=chart_ref_name,
        chart_ref_namespace=chart_ref_namespace,
        inline_values=inline_values,
        values_from_items=values_from_items if isinstance(values_from_items, list) else [],
        notes=notes,
        git_path=str(path),
    )


def _extract_source_url(source_doc: dict[str, Any] | None) -> str | None:
    if source_doc is None:
        return None
    return ((source_doc.get("spec") or {}).get("url")) or None


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _string_or_default(value: Any, default: str) -> str:
    return value if isinstance(value, str) else default
