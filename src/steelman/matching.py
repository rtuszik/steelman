from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .builtins import load_builtin_aliases
from .catalog import CatalogSnapshot
from .chart_values import resolve_chart_values
from .flux import (
    CurrentSource,
    DhiCatalogItem,
    DhiImageCatalogItem,
    ImageReference,
    ImageReplacement,
    InventoryItem,
    MatchResult,
)
from .identity import is_dhi_url, normalize_name, tokenize
from .image_values import extract_image_references, path_exists

MIN_LIKELY_SCORE = 4.5
MIN_AMBIGUOUS_SCORE = 4.0
AMBIGUOUS_DELTA = 0.75


@dataclass(frozen=True, slots=True)
class UserAlias:
    chart_name: str | None
    repo_url: str | None
    dhi_repo: str


@dataclass(slots=True)
class ChartMatch:
    status: str
    confidence: float
    replacement: CurrentSource | None
    reasons: list[str]
    evidence: list[str]


@dataclass(slots=True)
class ScoredChartCandidate:
    item: DhiCatalogItem
    score: float
    reasons: list[str]
    evidence: list[str]


def load_user_aliases(path: Path | None) -> list[UserAlias]:
    if path is None:
        return []
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    aliases: list[UserAlias] = []
    for alias in payload.get("aliases", []):
        match = alias.get("match") or {}
        aliases.append(
            UserAlias(
                chart_name=match.get("chartName"),
                repo_url=match.get("repoUrl"),
                dhi_repo=alias["dhiRepo"],
            )
        )
    return aliases


def match_inventory(
    items: list[InventoryItem],
    catalog: CatalogSnapshot,
    user_aliases: list[UserAlias] | None = None,
    *,
    skip_image_analysis: bool = False,
    helm_bin: str = "helm",
    image_match_threshold: float = 0.75,
) -> list[MatchResult]:
    chart_index = {item.dhi_repo: item for item in catalog.charts}
    image_index = list(catalog.images)
    aliases = user_aliases or []
    results = [
        match_item(
            item,
            catalog.charts,
            chart_index,
            image_index,
            aliases,
            skip_image_analysis=skip_image_analysis,
            helm_bin=helm_bin,
            image_match_threshold=image_match_threshold,
        )
        for item in items
    ]
    return sorted(results, key=_sort_match_result)


def match_item(
    item: InventoryItem,
    chart_catalog: list[DhiCatalogItem],
    chart_index: dict[str, DhiCatalogItem],
    image_catalog: list[DhiImageCatalogItem],
    user_aliases: list[UserAlias],
    *,
    skip_image_analysis: bool,
    helm_bin: str,
    image_match_threshold: float,
) -> MatchResult:
    current = item.current
    if current.source_kind == "oci" and is_dhi_url(current.source_url):
        chart_replacement = CurrentSource(
            source_kind="oci",
            source_url=current.source_url,
            chart_name=current.chart_name,
            version=current.version,
        )
        return MatchResult(
            release_name=item.release_name,
            cluster=item.cluster,
            namespace=item.namespace,
            origin=item.origin,
            current=current,
            identity=item.identity,
            recommendation_type="already_dhi_chart",
            chart_replacement=chart_replacement,
            image_replacements=[],
            chart_match_status="already-dhi",
            chart_match_confidence=1.0,
            chart_match_reasons=["Current chart source already points to dhi.io"],
            chart_match_evidence=[f"sourceUrl: {current.source_url}"],
            reasons=["Current chart source already points to dhi.io"],
            evidence=[f"sourceUrl: {current.source_url}"],
            notes=item.notes.copy(),
        )

    chart_match = _match_chart(item, chart_catalog, chart_index, user_aliases)
    analysis_notes: list[str] = []
    if chart_match.status == "ambiguous":
        analysis_notes.extend(chart_match.evidence)
    if chart_match.status in {"alias", "exact", "likely"}:
        return MatchResult(
            release_name=item.release_name,
            cluster=item.cluster,
            namespace=item.namespace,
            origin=item.origin,
            current=current,
            identity=item.identity,
            recommendation_type="hardened_chart_available",
            chart_replacement=chart_match.replacement,
            image_replacements=[],
            chart_match_status=chart_match.status,
            chart_match_confidence=chart_match.confidence,
            chart_match_reasons=chart_match.reasons,
            chart_match_evidence=chart_match.evidence,
            reasons=chart_match.reasons,
            evidence=chart_match.evidence,
            analysis_notes=analysis_notes,
            notes=item.notes.copy(),
        )

    if skip_image_analysis:
        analysis_notes.append("Image analysis skipped via CLI flag")
        return _build_none_result(item, chart_match, analysis_notes)

    image_replacements, image_notes = _match_images(
        item,
        image_catalog,
        helm_bin=helm_bin,
        image_match_threshold=image_match_threshold,
    )
    analysis_notes.extend(image_notes)
    if image_replacements:
        top = image_replacements[0]
        return MatchResult(
            release_name=item.release_name,
            cluster=item.cluster,
            namespace=item.namespace,
            origin=item.origin,
            current=current,
            identity=item.identity,
            recommendation_type="hardened_images_available",
            chart_replacement=None,
            image_replacements=image_replacements,
            chart_match_status=chart_match.status,
            chart_match_confidence=chart_match.confidence,
            chart_match_reasons=chart_match.reasons,
            chart_match_evidence=chart_match.evidence,
            reasons=[f"{len(image_replacements)} hardened image replacement(s) available"],
            evidence=[f"Top replacement: {top.path} -> {top.dhi_image_ref}"],
            analysis_notes=analysis_notes,
            notes=item.notes.copy(),
        )
    return _build_none_result(item, chart_match, analysis_notes)


def merge_inventory(
    git_items: list[InventoryItem],
    cluster_items: list[InventoryItem],
) -> list[InventoryItem]:
    if not cluster_items:
        return git_items
    merged: list[InventoryItem] = []
    used_git: set[int] = set()
    grouped_git: dict[tuple[str, str], list[tuple[int, InventoryItem]]] = {}
    for index, git_item in enumerate(git_items):
        grouped_git.setdefault((git_item.namespace, git_item.release_name), []).append(
            (index, git_item)
        )

    for cluster_item in cluster_items:
        candidates = grouped_git.get((cluster_item.namespace, cluster_item.release_name), [])
        if len(candidates) == 1:
            git_index, git_item = candidates[0]
            used_git.add(git_index)
            merged.append(_merge_item_pair(git_item, cluster_item))
        else:
            merged.append(cluster_item)

    for index, git_item in enumerate(git_items):
        if index not in used_git:
            merged.append(git_item)
    return sorted(merged, key=_sort_inventory_item)


def _merge_item_pair(git_item: InventoryItem, cluster_item: InventoryItem) -> InventoryItem:
    notes = list(dict.fromkeys(cluster_item.notes + git_item.notes))
    if (
        git_item.current.source_url != cluster_item.current.source_url
        or git_item.current.chart_name != cluster_item.current.chart_name
    ):
        notes.append("Drift detected between Git and cluster inventory")
    return InventoryItem(
        release_name=cluster_item.release_name,
        namespace=cluster_item.namespace,
        cluster=cluster_item.cluster,
        origin="both",
        current=cluster_item.current,
        identity=cluster_item.identity if cluster_item.identity.project else git_item.identity,
        source_name=cluster_item.source_name or git_item.source_name,
        source_namespace=cluster_item.source_namespace or git_item.source_namespace,
        source_ref_kind=cluster_item.source_ref_kind or git_item.source_ref_kind,
        source_ref_name=cluster_item.source_ref_name or git_item.source_ref_name,
        source_ref_namespace=cluster_item.source_ref_namespace or git_item.source_ref_namespace,
        chart_ref_kind=cluster_item.chart_ref_kind or git_item.chart_ref_kind,
        chart_ref_name=cluster_item.chart_ref_name or git_item.chart_ref_name,
        chart_ref_namespace=cluster_item.chart_ref_namespace or git_item.chart_ref_namespace,
        inline_values=(
            cluster_item.inline_values
            if cluster_item.inline_values is not None
            else git_item.inline_values
        ),
        values_from_items=cluster_item.values_from_items or git_item.values_from_items,
        notes=notes,
        git_path=git_item.git_path,
    )


def _match_chart(
    item: InventoryItem,
    chart_catalog: list[DhiCatalogItem],
    chart_index: dict[str, DhiCatalogItem],
    user_aliases: list[UserAlias],
) -> ChartMatch:
    user_alias_match = _match_user_alias(item, user_aliases, chart_index)
    if user_alias_match is not None:
        return _build_chart_replacement(
            item,
            user_alias_match,
            "alias",
            0.99,
            ["User alias matched release to DHI repo"],
            [f"catalogRepo: {user_alias_match.dhi_repo}"],
        )

    builtin_alias_match = _match_builtin_alias(item, chart_index)
    if builtin_alias_match is not None:
        repo, reason = builtin_alias_match
        return _build_chart_replacement(
            item,
            repo,
            "alias",
            0.99,
            [reason],
            [f"catalogRepo: {repo.dhi_repo}"],
        )

    scored = [_score_chart_candidate(item, candidate) for candidate in chart_catalog]
    scored = [entry for entry in scored if entry.score > 0]
    scored.sort(key=lambda entry: entry.score, reverse=True)
    if not scored:
        return ChartMatch(status="none", confidence=0.0, replacement=None, reasons=[], evidence=[])
    top = scored[0]
    if (
        top.score >= MIN_AMBIGUOUS_SCORE
        and len(scored) > 1
        and scored[1].score >= MIN_AMBIGUOUS_SCORE
        and top.score - scored[1].score <= AMBIGUOUS_DELTA
    ):
        options = ", ".join(
            f"{candidate.item.dhi_repo} ({candidate.score:.1f})" for candidate in scored[:3]
        )
        return ChartMatch(
            status="ambiguous",
            confidence=min(top.score / 10, 0.89),
            replacement=None,
            reasons=["Multiple plausible DHI chart matches were found"],
            evidence=[f"Chart candidates: {options}"],
        )
    if top.score < MIN_LIKELY_SCORE:
        return ChartMatch(status="none", confidence=0.0, replacement=None, reasons=[], evidence=[])
    status = "exact" if top.score >= 8.0 else "likely"
    return _build_chart_replacement(
        item,
        top.item,
        status,
        min(top.score / 10, 0.99),
        top.reasons,
        top.evidence,
    )


def _match_images(
    item: InventoryItem,
    image_catalog: list[DhiImageCatalogItem],
    *,
    helm_bin: str,
    image_match_threshold: float,
) -> tuple[list[ImageReplacement], list[str]]:
    values_result = resolve_chart_values(item, helm_bin=helm_bin)
    notes = values_result.notes.copy()
    if values_result.merged is None:
        return [], notes
    source_for_path = lambda path: (  # noqa: E731
        "helmrelease-inline-values"
        if item.inline_values is not None and path_exists(item.inline_values, path)
        else "chart-defaults"
    )
    references = extract_image_references(values_result.merged, source_for_path)
    if not references:
        notes.append("No image references were discovered in effective values")
        return [], notes
    replacements = []
    for reference in references:
        replacement = _match_image_reference(reference, image_catalog, image_match_threshold)
        if replacement is not None:
            replacements.append(replacement)
    replacements.sort(key=lambda item: item.confidence, reverse=True)
    return replacements, notes


def _match_image_reference(
    reference: ImageReference,
    image_catalog: list[DhiImageCatalogItem],
    threshold: float,
) -> ImageReplacement | None:
    best: tuple[DhiImageCatalogItem, float, list[str], list[str]] | None = None
    current_repo = _normalize_repo(reference.repository)
    current_basename = _repo_basename(reference.repository)
    current_tokens = set(tokenize(reference.repository, current_basename))
    for candidate in image_catalog:
        candidate_repo = _normalize_repo(candidate.image_repo)
        candidate_basename = _repo_basename(candidate.image_repo)
        candidate_tokens = set(
            tokenize(candidate.image_repo, candidate.display_name, candidate.description)
        )
        confidence = 0.0
        reasons: list[str] = []
        evidence = [f"imageRepo: {candidate.image_repo}"]
        if current_repo == candidate_repo or current_repo.endswith(f"/{candidate_repo}"):
            confidence = 0.95
            reasons.append("Normalized image repo matches DHI image repo")
        elif current_basename and candidate_basename and current_basename == candidate_basename:
            confidence = 0.9
            reasons.append("Image repo basename matches DHI image basename")
        else:
            shared = current_tokens & candidate_tokens
            if len(shared) >= 2:
                confidence = 0.8
                reasons.append(f"Meaningful image repo tokens overlap: {', '.join(sorted(shared))}")
                evidence.append(f"sharedTokens: {', '.join(sorted(shared))}")
        if confidence < threshold:
            continue
        if best is None or confidence > best[1]:
            best = (candidate, confidence, reasons, evidence)
    if best is None:
        return None
    candidate, confidence, reasons, evidence = best
    return ImageReplacement(
        path=reference.path,
        current_image=reference.current_image(),
        current_repository=reference.repository,
        current_tag=reference.tag,
        dhi_image=candidate.image_repo,
        dhi_image_ref=candidate.image_ref(),
        confidence=confidence,
        reasons=reasons,
        evidence=evidence,
    )


def _match_user_alias(
    item: InventoryItem,
    aliases: list[UserAlias],
    chart_index: dict[str, DhiCatalogItem],
) -> DhiCatalogItem | None:
    for alias in aliases:
        if alias.chart_name and normalize_name(alias.chart_name) != normalize_name(
            item.current.chart_name
        ):
            continue
        if alias.repo_url and alias.repo_url != item.current.source_url:
            continue
        if alias.dhi_repo in chart_index:
            return chart_index[alias.dhi_repo]
    return None


def _match_builtin_alias(
    item: InventoryItem,
    chart_index: dict[str, DhiCatalogItem],
) -> tuple[DhiCatalogItem, str] | None:
    chart_name = normalize_name(item.current.chart_name)
    repo_url = (item.current.source_url or "").lower()
    for alias in load_builtin_aliases():
        if alias.chart_name and normalize_name(alias.chart_name) != chart_name:
            continue
        if alias.repo_contains and alias.repo_contains not in repo_url:
            continue
        repo = chart_index.get(alias.dhi_repo)
        if repo is not None:
            return repo, alias.reason
    return None


def _score_chart_candidate(item: InventoryItem, candidate: DhiCatalogItem) -> ScoredChartCandidate:
    score = 0.0
    reasons: list[str] = []
    evidence = [f"catalogRepo: {candidate.dhi_repo}"]
    candidate_name = normalize_name(candidate.dhi_repo)
    project = normalize_name(item.identity.project)
    chart_name = normalize_name(item.current.chart_name)
    if candidate_name and project and candidate_name == project:
        score += 6.0
        reasons.append("Normalized chart name exactly matches DHI repo name")
        evidence.append(f"project: {project}")
    elif candidate_name and chart_name and candidate_name == chart_name:
        score += 5.0
        reasons.append("Normalized current chart name matches DHI repo name")
        evidence.append(f"chartName: {chart_name}")

    current_tokens = set(item.identity.tokens)
    candidate_tokens = set(
        tokenize(candidate.dhi_repo, candidate.display_name, candidate.description)
    )
    shared = current_tokens & candidate_tokens
    if shared:
        token_score = min(len(shared), 4)
        score += token_score
        reasons.append(f"Shared normalized tokens: {', '.join(sorted(shared))}")
        evidence.append(f"sharedTokens: {', '.join(sorted(shared))}")

    if item.identity.vendor and item.identity.vendor in candidate_tokens:
        score += 1.5
        reasons.append("Vendor token aligns with the candidate repo")
        evidence.append(f"vendor: {item.identity.vendor}")

    if item.current.source_url and any(
        link
        for link in candidate.documentation_links
        if _same_domain(link, item.current.source_url)
    ):
        score += 1.0
        reasons.append("Documentation domain overlaps with current source URL")

    return ScoredChartCandidate(item=candidate, score=score, reasons=reasons, evidence=evidence)


def _build_chart_replacement(
    item: InventoryItem,
    repo: DhiCatalogItem,
    status: str,
    confidence: float,
    reasons: list[str],
    evidence: list[str],
) -> ChartMatch:
    return ChartMatch(
        status=status,
        confidence=confidence,
        replacement=CurrentSource(
            source_kind="oci",
            source_url=repo.target_url(),
            chart_name=repo.dhi_repo,
            version=None,
        ),
        reasons=reasons,
        evidence=evidence,
    )


def _build_none_result(
    item: InventoryItem,
    chart_match: ChartMatch,
    analysis_notes: list[str],
) -> MatchResult:
    return MatchResult(
        release_name=item.release_name,
        cluster=item.cluster,
        namespace=item.namespace,
        origin=item.origin,
        current=item.current,
        identity=item.identity,
        recommendation_type="none",
        chart_replacement=None,
        image_replacements=[],
        chart_match_status=chart_match.status,
        chart_match_confidence=chart_match.confidence,
        chart_match_reasons=chart_match.reasons,
        chart_match_evidence=chart_match.evidence,
        reasons=["No DHI chart or image replacement was found"],
        evidence=[],
        analysis_notes=analysis_notes,
        notes=item.notes.copy(),
    )


def _normalize_repo(value: str) -> str:
    normalized = value.lower().replace("_", "-").strip("/")
    return normalized


def _repo_basename(value: str) -> str | None:
    normalized = _normalize_repo(value)
    if not normalized:
        return None
    return normalized.rsplit("/", 1)[-1]


def _same_domain(left: str, right: str) -> bool:
    return left.split("/")[2].lower() == right.split("/")[2].lower()


def _sort_match_result(item: MatchResult) -> tuple[str, str, str]:
    return ((item.cluster or ""), item.namespace, item.release_name)


def _sort_inventory_item(item: InventoryItem) -> tuple[str, str, str]:
    return ((item.cluster or ""), item.namespace, item.release_name)
