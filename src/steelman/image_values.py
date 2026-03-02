from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .flux import ImageReference


def extract_image_references(
    values: Any,
    source_for_path: Callable[[str], str] | None = None,
) -> list[ImageReference]:
    references: list[ImageReference] = []
    _walk(values, [], references, source_for_path)
    deduped: dict[tuple[str, str, str | None, str | None], ImageReference] = {}
    for reference in references:
        key = (reference.path, reference.repository, reference.tag, reference.digest)
        deduped[key] = reference
    return sorted(deduped.values(), key=lambda item: item.path)


def path_exists(values: Any, path: str) -> bool:
    current = values
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


def _walk(
    value: Any,
    path: list[str],
    references: list[ImageReference],
    source_for_path: Callable[[str], str] | None,
) -> None:
    if isinstance(value, dict):
        parent_key = path[-1].lower() if path else ""
        image_ref = _parse_image_object(value, path, parent_key, source_for_path)
        if image_ref is not None:
            references.append(image_ref)
        for key, nested in value.items():
            if isinstance(key, str):
                _walk(nested, [*path, key], references, source_for_path)
    elif isinstance(value, str) and path:
        leaf_key = path[-1].lower()
        if "image" in leaf_key:
            parsed = _parse_image_string(value)
            if parsed is not None:
                repository, registry, tag, digest = parsed
                references.append(
                    ImageReference(
                        path=".".join(path),
                        repository=repository,
                        registry=registry,
                        tag=tag,
                        digest=digest,
                        raw=value,
                        source=_source_for_path(".".join(path), source_for_path),
                    )
                )


def _parse_image_object(
    value: dict[str, Any],
    path: list[str],
    parent_key: str,
    source_for_path: Callable[[str], str] | None,
) -> ImageReference | None:
    if "image" not in parent_key:
        return None
    repository_key = next((key for key in ("repository", "repo", "name") if key in value), None)
    if repository_key is None or not isinstance(value.get(repository_key), str):
        return None
    repository = value[repository_key]
    registry = value.get("registry") if isinstance(value.get("registry"), str) else None
    tag = value.get("tag") if isinstance(value.get("tag"), str) else None
    digest = value.get("digest") if isinstance(value.get("digest"), str) else None
    raw = _build_image_raw(registry, repository, tag, digest)
    return ImageReference(
        path=".".join([*path, repository_key]),
        repository=repository,
        registry=registry,
        tag=tag,
        digest=digest,
        raw=raw,
        source=_source_for_path(".".join([*path, repository_key]), source_for_path),
    )


def _parse_image_string(value: str) -> tuple[str, str | None, str | None, str | None] | None:
    candidate = value.strip()
    if not candidate or "/" not in candidate:
        return None
    repository_and_tag, _, digest = candidate.partition("@")
    last_segment = repository_and_tag.rsplit("/", 1)[-1]
    tag = None
    if ":" in last_segment:
        repository, tag = repository_and_tag.rsplit(":", 1)
    else:
        repository = repository_and_tag
    parts = repository.split("/")
    registry = parts[0] if "." in parts[0] or ":" in parts[0] else None
    if registry:
        repository = "/".join(parts[1:])
    return (repository, registry, tag, digest or None)


def _build_image_raw(
    registry: str | None,
    repository: str,
    tag: str | None,
    digest: str | None,
) -> str:
    base = f"{registry}/{repository}" if registry else repository
    if digest:
        return f"{base}@{digest}"
    if tag:
        return f"{base}:{tag}"
    return base


def _source_for_path(path: str, source_for_path: Callable[[str], str] | None) -> str:
    if source_for_path is None:
        return "chart-defaults"
    return source_for_path(path)
