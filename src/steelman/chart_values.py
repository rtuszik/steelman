from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

import yaml

from .flux import InventoryItem


@dataclass(slots=True)
class ChartValuesResult:
    defaults: Any | None
    merged: Any | None
    notes: list[str]


def resolve_chart_values(item: InventoryItem, helm_bin: str = "helm") -> ChartValuesResult:
    notes: list[str] = []
    if shutil.which(helm_bin) is None:
        return ChartValuesResult(
            defaults=None,
            merged=None,
            notes=[f"Helm binary '{helm_bin}' not found; skipping image analysis"],
        )
    if item.values_from_items:
        notes.append("valuesFrom present but not resolved in v1")
    command = _build_helm_command(item, helm_bin)
    if command is None:
        notes.append("Release does not expose enough chart metadata to fetch defaults")
        return ChartValuesResult(defaults=None, merged=None, notes=notes)
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        notes.append(f"helm show values failed: {message}")
        return ChartValuesResult(defaults=None, merged=None, notes=notes)
    defaults = yaml.safe_load(completed.stdout) or {}
    if not isinstance(defaults, dict):
        notes.append("helm show values returned a non-mapping document")
        return ChartValuesResult(defaults=None, merged=None, notes=notes)
    merged = deep_merge(defaults, item.inline_values)
    notes.append("Chart defaults resolved with helm show values")
    if item.inline_values is not None:
        notes.append("Inline HelmRelease values merged over chart defaults")
    return ChartValuesResult(defaults=defaults, merged=merged, notes=notes)


def _build_helm_command(item: InventoryItem, helm_bin: str) -> list[str] | None:
    if not item.current.source_url:
        return None
    if item.current.source_kind == "helm":
        if not item.current.chart_name:
            return None
        command = [
            helm_bin,
            "show",
            "values",
            item.current.chart_name,
            "--repo",
            item.current.source_url,
        ]
    elif item.current.source_kind == "oci":
        command = [helm_bin, "show", "values", item.current.source_url]
    else:
        return None
    if item.current.version:
        command.extend(["--version", item.current.version])
    return command


def deep_merge(base: Any, override: Any) -> Any:
    if override is None:
        return base
    if base is None:
        return override
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = deep_merge(merged.get(key), value)
        return merged
    return override
