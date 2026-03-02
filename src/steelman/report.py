from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .catalog import CatalogSnapshot
from .flux import MatchResult, ScanError


def write_reports(
    output_dir: Path,
    catalog: CatalogSnapshot,
    results: list[MatchResult],
    errors: list[ScanError],
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / "steelman.md"
    json_path = output_dir / "steelman.json"
    markdown_path.write_text(render_markdown(catalog, results, errors), encoding="utf-8")
    json_path.write_text(
        json.dumps(render_json(catalog, results, errors), indent=2), encoding="utf-8"
    )
    return markdown_path, json_path


def render_json(
    catalog: CatalogSnapshot,
    results: list[MatchResult],
    errors: list[ScanError],
) -> dict[str, Any]:
    statuses = Counter(result.recommendation_type for result in results)
    inventory = Counter(result.origin for result in results)
    return {
        "generatedAt": catalog.fetched_at,
        "catalog": catalog.to_dict(),
        "inventory": {
            "totalReleases": len(results),
            "origins": dict(sorted(inventory.items())),
        },
        "summary": {
            "total": len(results),
            "recommendationCounts": dict(sorted(statuses.items())),
        },
        "results": [result.to_dict() for result in results],
        "errors": [error.to_dict() for error in errors],
    }


def render_markdown(
    catalog: CatalogSnapshot,
    results: list[MatchResult],
    errors: list[ScanError],
) -> str:
    statuses = Counter(result.recommendation_type for result in results)
    sections = [
        "# DHI Chart Migration Report",
        "",
        "## Summary",
        "",
        f"- Catalog fetched at: `{catalog.fetched_at}`",
        f"- DHI charts in catalog: `{len(catalog.charts)}`",
        f"- DHI images in catalog: `{len(catalog.images)}`",
        f"- Total releases: `{len(results)}`",
    ]
    for status, count in sorted(statuses.items()):
        sections.append(f"- {status}: `{count}`")
    if catalog.degraded:
        sections.append("- Catalog mode: `degraded`")
    sections.append("")

    sections.extend(
        _render_chart_section("Already on DHI Chart", results, {"already_dhi_chart"})
    )
    sections.extend(
        _render_chart_section(
            "Hardened Chart Available",
            results,
            {"hardened_chart_available"},
        )
    )
    sections.extend(
        _render_image_section(
            "Hardened Images Available",
            results,
            {"hardened_images_available"},
        )
    )
    sections.extend(_render_none_section("No DHI Replacement", results, {"none"}))

    sections.append("## Scan Notes")
    sections.append("")
    notes = []
    for result in results:
        for note in result.notes:
            notes.append(f"- `{result.release_name}`: {note}")
        for note in result.analysis_notes:
            notes.append(f"- `{result.release_name}`: {note}")
    for note in catalog.notes or []:
        notes.append(f"- Catalog: {note}")
    for error in errors:
        notes.append(f"- {error.source}: {error.message}")
    if notes:
        sections.extend(notes)
    else:
        sections.append("- None")
    sections.append("")
    return "\n".join(sections)


def _render_chart_section(title: str, results: list[MatchResult], statuses: set[str]) -> list[str]:
    section = [f"## {title}", ""]
    filtered = [result for result in results if result.recommendation_type in statuses]
    if not filtered:
        section.append("- None")
        section.append("")
        return section
    header = (
        "| Cluster | Namespace | Release | Current Chart | Current Source | "
        "Recommended DHI Chart | Confidence | Rationale |"
    )
    section.append(header)
    section.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for result in filtered:
        rationale = "; ".join([*result.reasons, *result.evidence]) or "-"
        row = (
            "| {cluster} | {namespace} | {release} | {chart} | {source} | {target} | "
            "{confidence:.2f} | {rationale} |"
        )
        section.append(
            row.format(
                cluster=result.cluster or "git",
                namespace=result.namespace,
                release=result.release_name,
                source=result.current.source_url or "-",
                chart=result.current.chart_name or "-",
                target=result.chart_replacement.source_url if result.chart_replacement else "-",
                confidence=result.chart_match_confidence,
                rationale=rationale.replace("|", "/"),
            )
        )
    section.append("")
    return section


def _render_image_section(title: str, results: list[MatchResult], statuses: set[str]) -> list[str]:
    section = [f"## {title}", ""]
    filtered = [result for result in results if result.recommendation_type in statuses]
    if not filtered:
        section.append("- None")
        section.append("")
        return section
    section.append(
        "| Cluster | Namespace | Release | Current Chart | Image Replacements | "
        "Top Replacement | Rationale |"
    )
    section.append("| --- | --- | --- | --- | --- | --- | --- |")
    for result in filtered:
        top = result.image_replacements[0]
        row = (
            "| {cluster} | {namespace} | {release} | {chart} | {count} | "
            "{top} | {rationale} |"
        )
        section.append(
            row.format(
                cluster=result.cluster or "git",
                namespace=result.namespace,
                release=result.release_name,
                chart=result.current.chart_name or "-",
                count=len(result.image_replacements),
                top=f"{top.path} -> {top.dhi_image_ref}",
                rationale="; ".join(result.reasons).replace("|", "/"),
            )
        )
    section.append("")
    section.append("### Image Details")
    section.append("")
    for result in filtered:
        section.append(f"#### {result.release_name}")
        for replacement in result.image_replacements:
            rationale = "; ".join(replacement.reasons)
            section.append(
                f"- `{replacement.path}`: "
                f"`{replacement.current_image}` -> `{replacement.dhi_image_ref}` "
                f"({replacement.confidence:.2f}) {rationale}"
            )
        section.append("")
    return section


def _render_none_section(title: str, results: list[MatchResult], statuses: set[str]) -> list[str]:
    section = [f"## {title}", ""]
    filtered = [result for result in results if result.recommendation_type in statuses]
    if not filtered:
        section.append("- None")
        section.append("")
        return section
    section.append("| Cluster | Namespace | Release | Current Chart | Current Source | Notes |")
    section.append("| --- | --- | --- | --- | --- | --- |")
    for result in filtered:
        notes = "; ".join([*result.reasons, *result.analysis_notes]) or "-"
        section.append(
            "| {cluster} | {namespace} | {release} | {chart} | {source} | {notes} |".format(
                cluster=result.cluster or "git",
                namespace=result.namespace,
                release=result.release_name,
                chart=result.current.chart_name or "-",
                source=result.current.source_url or "-",
                notes=notes.replace("|", "/"),
            )
        )
    section.append("")
    return section
