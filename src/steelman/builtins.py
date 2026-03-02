from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Any


@dataclass(frozen=True, slots=True)
class AliasRule:
    chart_name: str | None
    repo_contains: str | None
    dhi_repo: str
    reason: str


def load_builtin_aliases() -> list[AliasRule]:
    payload = _load_alias_payload()
    aliases: list[AliasRule] = []
    for alias in payload:
        aliases.append(
            AliasRule(
                chart_name=_string_or_none(alias.get("chartName")),
                repo_contains=_string_or_none(alias.get("repoContains")),
                dhi_repo=str(alias["dhiRepo"]),
                reason=str(alias["reason"]),
            )
        )
    return aliases


def _load_alias_payload() -> list[dict[str, Any]]:
    builtins_path = files("steelman").joinpath("builtins_aliases.json")
    with builtins_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    aliases = payload.get("aliases", [])
    if not isinstance(aliases, list):
        raise ValueError("builtins_aliases.json must contain an 'aliases' list")
    return [item for item in aliases if isinstance(item, dict)]


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None
