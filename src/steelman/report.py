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
    *,
    include_already_migrated: bool = False,
) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / "steelman.md"
    json_path = output_dir / "steelman.json"
    issue_path = output_dir / "steelman-issue.md"
    markdown_path.write_text(
        render_markdown(
            catalog,
            results,
            errors,
            include_already_migrated=include_already_migrated,
        ),
        encoding="utf-8",
    )
    json_path.write_text(
        json.dumps(render_json(catalog, results, errors), indent=2), encoding="utf-8"
    )
    issue_path.write_text(
        render_issue_markdown(catalog, results, errors),
        encoding="utf-8",
    )
    return markdown_path, json_path, issue_path


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
    *,
    include_already_migrated: bool = False,
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

    if include_already_migrated:
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


def render_issue_markdown(
    catalog: CatalogSnapshot,
    results: list[MatchResult],
    errors: list[ScanError],
) -> str:
    statuses = Counter(result.recommendation_type for result in results)
    actionable = [
        result
        for result in results
        if result.recommendation_type in {"hardened_chart_available", "hardened_images_available"}
    ]
    already_done = [
        result for result in results if result.recommendation_type == "already_dhi_chart"
    ]
    no_replacement = [result for result in results if result.recommendation_type == "none"]

    sections = [
        "# DHI Implementation Status",
        "",
        "This issue is managed by `steelman` in CI/CD and tracks current DHI migration status.",
        "",
        "## Snapshot",
        "",
        f"- Catalog fetched at: `{catalog.fetched_at}`",
        f"- Total releases tracked: `{len(results)}`",
        f"- Already on DHI: `{statuses.get('already_dhi_chart', 0)}`",
        f"- Chart migrations available: `{statuses.get('hardened_chart_available', 0)}`",
        f"- Image migrations available: `{statuses.get('hardened_images_available', 0)}`",
        f"- No DHI replacement found: `{statuses.get('none', 0)}`",
    ]
    if catalog.degraded:
        sections.append("- Catalog mode: `degraded`")
    sections.extend(["", "## Migration Checklist", ""])

    if not results:
        sections.append("- No Helm releases were detected.")
    else:
        sections.extend(
            _render_issue_checklist(
                "Pending chart migrations",
                actionable,
                "hardened_chart_available",
            )
        )
        sections.extend(
            _render_issue_checklist(
                "Pending image migrations",
                actionable,
                "hardened_images_available",
            )
        )
        sections.extend(
            _render_issue_checklist("Already on DHI", already_done, "already_dhi_chart")
        )
        sections.extend(_render_issue_notes("No DHI replacement", no_replacement))

    sections.extend(
        [
            "",
            "## Artifacts",
            "",
            "- Full report: `reports/steelman.md`",
            "- Machine-readable report: `reports/steelman.json`",
        ]
    )

    sections.extend(["", "## Scan Notes", ""])
    if errors:
        for error in errors:
            sections.append(f"- {error.source}: {error.message}")
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
        row = "| {cluster} | {namespace} | {release} | {chart} | {count} | {top} | {rationale} |"
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


def _render_issue_checklist(
    title: str,
    results: list[MatchResult],
    status: str,
) -> list[str]:
    section = [f"### {title}", ""]
    filtered = [result for result in results if result.recommendation_type == status]
    if not filtered:
        section.extend(["- None", ""])
        return section
    checked = "x" if status == "already_dhi_chart" else " "
    for result in filtered:
        section.append(
            f"- [{checked}] `{result.namespace}/{result.release_name}` ({result.cluster or 'git'})"
        )
        summary = _issue_result_summary(result)
        if summary:
            section.append(f"  - {summary}")
    section.append("")
    return section


def _render_issue_notes(title: str, results: list[MatchResult]) -> list[str]:
    section = [f"### {title}", ""]
    if not results:
        section.extend(["- None", ""])
        return section
    for result in results:
        section.append(
            f"- `{result.namespace}/{result.release_name}` "
            f"({result.cluster or 'git'}): {_issue_result_summary(result)}"
        )
    section.append("")
    return section


def _issue_result_summary(result: MatchResult) -> str:
    if result.recommendation_type == "hardened_chart_available" and result.chart_replacement:
        target = result.chart_replacement.source_url or result.chart_replacement.chart_name or "-"
        return f"Replace chart `{result.current.chart_name or '-'}` with `{target}`."
    if result.recommendation_type == "hardened_images_available" and result.image_replacements:
        top = result.image_replacements[0]
        return f"Update `{top.path}` from `{top.current_image}` to `{top.dhi_image_ref}`."
    if result.recommendation_type == "already_dhi_chart":
        current = result.current.source_url or result.current.chart_name or "-"
        return f"Current chart source: `{current}`."
    return "; ".join([*result.reasons, *result.analysis_notes]) or "-"
