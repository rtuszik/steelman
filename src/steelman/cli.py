from __future__ import annotations

import argparse
import logging
import shutil
from pathlib import Path

from .catalog import fetch_catalog
from .flux import InventoryItem, ScanError
from .inventory_cluster import discover_contexts, scan_contexts
from .inventory_git import scan_repo
from .matching import load_user_aliases, match_inventory, merge_inventory
from .report import write_reports

LOGGER = logging.getLogger("steelman")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="steelman",
        description="Report Flux Helm releases that have DHI OCI chart replacements.",
    )
    parser.add_argument("--mode", choices=("git", "cluster", "both"), default="both")
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--contexts", help="Comma-separated kube contexts to scan")
    parser.add_argument("--output-dir", type=Path, default=Path("."))
    parser.add_argument("--aliases", type=Path)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--no-cluster", action="store_true")
    parser.add_argument("--no-git", action="store_true")
    parser.add_argument("--skip-image-analysis", action="store_true")
    parser.add_argument(
        "--include-already-migrated",
        action="store_true",
        help="Include releases already using DHI charts in the Markdown report",
    )
    parser.add_argument("--helm-bin", default="helm")
    parser.add_argument("--image-match-threshold", type=float, default=0.75)
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _configure_logging(verbose=args.verbose)

    LOGGER.info("Starting steelman")
    catalog = fetch_catalog(offline=args.offline)
    LOGGER.info(
        "Loaded DHI catalog: %s charts, %s images%s",
        len(catalog.charts),
        len(catalog.images),
        " (degraded)" if catalog.degraded else "",
    )

    git_items: list[InventoryItem] = []
    cluster_items: list[InventoryItem] = []
    errors: list[ScanError] = []

    use_git = args.mode in {"git", "both"} and not args.no_git
    use_cluster = args.mode in {"cluster", "both"} and not args.no_cluster

    if not args.skip_image_analysis and shutil.which(args.helm_bin) is None:
        message = f"Helm binary '{args.helm_bin}' not found; image analysis will be skipped"
        errors.append(ScanError(source="helm", message=message))
        LOGGER.warning(message)

    if use_git:
        LOGGER.info("Scanning Git manifests under %s", args.repo)
        repo_items, repo_errors = scan_repo(args.repo)
        git_items.extend(repo_items)
        errors.extend(repo_errors)
        LOGGER.info(
            "Git scan complete: %s releases, %s errors",
            len(repo_items),
            len(repo_errors),
        )

    if use_cluster:
        try:
            contexts = [
                item for item in (args.contexts or "").split(",") if item
            ] or discover_contexts()
            LOGGER.info("Scanning cluster state from contexts: %s", ", ".join(contexts) or "<none>")
            live_items, live_errors = scan_contexts(contexts)
            cluster_items.extend(live_items)
            errors.extend(live_errors)
            LOGGER.info(
                "Cluster scan complete: %s releases, %s errors",
                len(live_items),
                len(live_errors),
            )
        except Exception as exc:
            errors.append(ScanError(source="kubeconfig", message=str(exc)))
            LOGGER.exception("Failed to initialize cluster scanning")

    if args.mode == "git" or args.no_cluster:
        items = git_items
    elif args.mode == "cluster" or args.no_git:
        items = cluster_items
    else:
        items = merge_inventory(git_items, cluster_items)
    LOGGER.info("Prepared %s release records for analysis", len(items))

    user_aliases = load_user_aliases(args.aliases)
    if args.aliases:
        LOGGER.info("Loaded %s user aliases from %s", len(user_aliases), args.aliases)
    results = match_inventory(
        items,
        catalog,
        user_aliases,
        skip_image_analysis=args.skip_image_analysis,
        helm_bin=args.helm_bin,
        image_match_threshold=args.image_match_threshold,
    )
    recommendation_counts: dict[str, int] = {}
    for result in results:
        recommendation_counts[result.recommendation_type] = (
            recommendation_counts.get(result.recommendation_type, 0) + 1
        )
    LOGGER.info("Recommendation summary: %s", recommendation_counts)
    markdown_path, json_path, issue_path = write_reports(
        args.output_dir,
        catalog,
        results,
        errors,
        include_already_migrated=args.include_already_migrated,
    )
    LOGGER.info("Wrote reports: %s, %s, and %s", markdown_path, json_path, issue_path)
    if errors:
        LOGGER.warning("Completed with %s recorded scan errors", len(errors))
    else:
        LOGGER.info("Completed successfully")
    return 0


def _configure_logging(*, verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(message)s",
    )
