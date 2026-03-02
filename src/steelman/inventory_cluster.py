from __future__ import annotations

from typing import Any

from kubernetes import client, config

from .flux import CurrentSource, InventoryItem, ScanError
from .identity import build_identity

HELM_GROUP = "helm.toolkit.fluxcd.io"
HELM_VERSION = "v2"
SOURCE_GROUP = "source.toolkit.fluxcd.io"
SOURCE_VERSION = "v1"

SOURCE_KINDS = {
    "HelmRepository": "helm",
    "OCIRepository": "oci",
}


def discover_contexts() -> list[str]:
    contexts, current = config.list_kube_config_contexts()
    names = [item["name"] for item in contexts]
    if not names:
        return []
    if len(names) <= 10:
        return names
    if current:
        return [current["name"]]
    return [names[0]]


def scan_contexts(context_names: list[str]) -> tuple[list[InventoryItem], list[ScanError]]:
    items: list[InventoryItem] = []
    errors: list[ScanError] = []
    for context_name in context_names:
        try:
            context_items = _scan_context(context_name)
            items.extend(context_items)
        except Exception as exc:
            errors.append(ScanError(source=f"kube:{context_name}", message=str(exc)))
    return items, errors


def _scan_context(context_name: str) -> list[InventoryItem]:
    api_client = config.new_client_from_config(context=context_name)
    custom_api = client.CustomObjectsApi(api_client)
    helm_releases = custom_api.list_cluster_custom_object(
        group=HELM_GROUP,
        version=HELM_VERSION,
        plural="helmreleases",
    )["items"]
    helm_repositories = custom_api.list_cluster_custom_object(
        group=SOURCE_GROUP,
        version=SOURCE_VERSION,
        plural="helmrepositories",
    )["items"]
    oci_repositories = custom_api.list_cluster_custom_object(
        group=SOURCE_GROUP,
        version=SOURCE_VERSION,
        plural="ocirepositories",
    )["items"]
    source_index: dict[tuple[str, str, str], dict[str, Any]] = {}
    for document in helm_repositories + oci_repositories:
        metadata = document.get("metadata") or {}
        source_index[(document["kind"], metadata.get("namespace", "default"), metadata["name"])] = (
            document
        )
    items = []
    for document in helm_releases:
        items.append(_helm_release_to_item(document, context_name, source_index))
    return items


def _helm_release_to_item(
    document: dict[str, Any],
    context_name: str,
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
        cluster=context_name,
        origin="cluster",
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
    )


def _extract_source_url(source_doc: dict[str, Any] | None) -> str | None:
    if source_doc is None:
        return None
    return ((source_doc.get("spec") or {}).get("url")) or None


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _string_or_default(value: Any, default: str) -> str:
    return value if isinstance(value, str) else default
