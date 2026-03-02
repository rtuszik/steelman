from __future__ import annotations

from steelman.chart_values import deep_merge


def test_deep_merge_overlays_inline_values() -> None:
    merged = deep_merge(
        {"image": {"repository": "ghcr.io/kyverno/kyverno", "tag": "v1.12.0"}},
        {"image": {"tag": "v1.13.0"}},
    )
    assert merged == {"image": {"repository": "ghcr.io/kyverno/kyverno", "tag": "v1.13.0"}}
