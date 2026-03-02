from __future__ import annotations

from steelman.catalog import CatalogSnapshot
from steelman.flux import (
    ChartIdentity,
    CurrentSource,
    DhiCatalogItem,
    DhiImageCatalogItem,
    InventoryItem,
)
from steelman.matching import match_inventory


def _catalog(
    chart_repos: tuple[str, ...] = (),
    image_repos: tuple[str, ...] = (),
) -> CatalogSnapshot:
    return CatalogSnapshot(
        charts=[
            DhiCatalogItem(
                dhi_repo=repo,
                display_name=repo,
                description=None,
                documentation_links=[],
                path=f"chart/{repo}",
            )
            for repo in chart_repos
        ],
        images=[
            DhiImageCatalogItem(
                image_repo=repo,
                display_name=repo,
                description=None,
                documentation_links=[],
                path=f"image/{repo}",
            )
            for repo in image_repos
        ],
        fetched_at="2026-03-02T00:00:00+00:00",
        source="test",
    )


def _item(chart_name: str, source_url: str, source_kind: str = "helm") -> InventoryItem:
    current = CurrentSource(
        source_kind=source_kind,
        source_url=source_url,
        chart_name=chart_name,
        version=None,
    )
    identity = ChartIdentity(
        project=chart_name,
        vendor="stakater" if "stakater" in source_url else None,
        repo_url=source_url,
        tokens=sorted(
            set(chart_name.replace("-", " ").split()) | set(source_url.replace("/", " ").split())
        ),
    )
    return InventoryItem(
        release_name=chart_name,
        namespace="default",
        cluster="prod",
        origin="cluster",
        current=current,
        identity=identity,
    )


def test_builtin_alias_matches_external_dns_chart() -> None:
    results = match_inventory(
        [_item("external-dns", "https://kubernetes-sigs.github.io/external-dns/")],
        _catalog(chart_repos=("external-dns-chart",)),
        skip_image_analysis=True,
    )
    assert results[0].recommendation_type == "hardened_chart_available"
    assert results[0].chart_replacement is not None
    assert results[0].chart_replacement.source_url == "oci://dhi.io/external-dns-chart"


def test_marks_existing_dhi_chart_as_already_dhi() -> None:
    results = match_inventory(
        [_item("external-dns", "oci://dhi.io/external-dns-chart", source_kind="oci")],
        _catalog(chart_repos=("external-dns-chart",)),
        skip_image_analysis=True,
    )
    assert results[0].recommendation_type == "already_dhi_chart"


def test_weak_chart_overlap_falls_back_to_none() -> None:
    results = match_inventory(
        [_item("kyverno", "https://kyverno.github.io/kyverno/")],
        _catalog(chart_repos=("kyverno-policy-reporter",)),
        skip_image_analysis=True,
    )
    assert results[0].recommendation_type == "none"


def test_image_match_uses_helm_defaults(monkeypatch) -> None:
    item = _item("kyverno", "https://kyverno.github.io/kyverno/")

    def fake_resolve_chart_values(*args, **kwargs):
        from steelman.chart_values import ChartValuesResult

        return ChartValuesResult(
            defaults={"image": {"repository": "ghcr.io/kyverno/kyverno", "tag": "v1.13.0"}},
            merged={"image": {"repository": "ghcr.io/kyverno/kyverno", "tag": "v1.13.0"}},
            notes=["Chart defaults resolved with helm show values"],
        )

    monkeypatch.setattr("steelman.matching.resolve_chart_values", fake_resolve_chart_values)

    results = match_inventory(
        [item],
        _catalog(image_repos=("kyverno",)),
    )
    assert results[0].recommendation_type == "hardened_images_available"
    assert results[0].image_replacements[0].dhi_image_ref == "dhi.io/kyverno"
