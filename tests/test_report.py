from __future__ import annotations

from steelman.catalog import CatalogSnapshot
from steelman.flux import (
    ChartIdentity,
    CurrentSource,
    ImageReplacement,
    MatchResult,
    ScanError,
)
from steelman.report import render_json, render_markdown


def _snapshot() -> CatalogSnapshot:
    return CatalogSnapshot(
        charts=[],
        images=[],
        fetched_at="2026-03-02T00:00:00+00:00",
        source="test",
    )


def test_render_report_contains_tiered_sections() -> None:
    result = MatchResult(
        release_name="external-dns",
        cluster="prod",
        namespace="networking",
        origin="cluster",
        current=CurrentSource(
            source_kind="helm",
            source_url="https://kubernetes-sigs.github.io/external-dns/",
            chart_name="external-dns",
            version="1.18.0",
        ),
        identity=ChartIdentity(
            project="external-dns",
            vendor=None,
            repo_url="https://kubernetes-sigs.github.io/external-dns/",
            tokens=["external", "dns"],
        ),
        recommendation_type="hardened_chart_available",
        chart_replacement=CurrentSource(
            source_kind="oci",
            source_url="oci://dhi.io/external-dns-chart",
            chart_name="external-dns-chart",
            version=None,
        ),
        image_replacements=[],
        chart_match_status="alias",
        chart_match_confidence=0.99,
        chart_match_reasons=["Built-in alias matched release to DHI repo"],
        chart_match_evidence=["catalogRepo: external-dns-chart"],
        reasons=["Built-in alias matched release to DHI repo"],
        evidence=["catalogRepo: external-dns-chart"],
    )
    markdown = render_markdown(_snapshot(), [result], [ScanError(source="repo", message="warn")])
    payload = render_json(_snapshot(), [result], [])
    assert "Hardened Chart Available" in markdown
    assert payload["summary"]["recommendationCounts"]["hardened_chart_available"] == 1


def test_render_report_includes_image_details() -> None:
    result = MatchResult(
        release_name="kyverno",
        cluster="prod",
        namespace="kyverno",
        origin="cluster",
        current=CurrentSource(
            source_kind="helm",
            source_url="https://kyverno.github.io/kyverno/",
            chart_name="kyverno",
            version=None,
        ),
        identity=ChartIdentity(
            project="kyverno",
            vendor="kyverno",
            repo_url="https://kyverno.github.io/kyverno/",
            tokens=["kyverno"],
        ),
        recommendation_type="hardened_images_available",
        chart_replacement=None,
        image_replacements=[
            ImageReplacement(
                path="image.repository",
                current_image="ghcr.io/kyverno/kyverno:v1.13.0",
                current_repository="kyverno/kyverno",
                current_tag="v1.13.0",
                dhi_image="kyverno",
                dhi_image_ref="dhi.io/kyverno",
                confidence=0.93,
                reasons=["Normalized image repo matches DHI image repo"],
                evidence=[],
            )
        ],
        chart_match_status="none",
        chart_match_confidence=0.0,
        chart_match_reasons=[],
        chart_match_evidence=[],
        reasons=["1 hardened image replacement(s) available"],
        evidence=["Top replacement: image.repository -> dhi.io/kyverno"],
    )
    markdown = render_markdown(_snapshot(), [result], [])
    assert "Image Details" in markdown
    assert "dhi.io/kyverno" in markdown
