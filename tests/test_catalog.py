from __future__ import annotations

import io
import tarfile

from steelman.catalog import _load_cached_snapshot, parse_catalog_archive


def _archive(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, content in files.items():
            payload = content.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def test_parse_catalog_archive_includes_charts_and_images() -> None:
    content = _archive(
        {
            "catalog-main/chart/external-dns-chart/info.yaml": """
name: External DNS
description: Hardened external dns chart
docs:
  - https://kubernetes-sigs.github.io/external-dns/
""",
            "catalog-main/image/kyverno/info.yaml": """
name: kyverno
description: Hardened kyverno image
docs:
  - https://github.com/kyverno/kyverno
""",
        }
    )
    snapshot = parse_catalog_archive(content)
    assert len(snapshot.charts) == 1
    assert len(snapshot.images) == 1
    assert snapshot.charts[0].dhi_repo == "external-dns-chart"
    assert snapshot.images[0].image_repo == "kyverno"


def test_legacy_cache_shape_is_ignored(tmp_path, monkeypatch) -> None:
    cache_file = tmp_path / "catalog.json"
    cache_file.write_text(
        '{"fetchedAt":"2026-03-02T00:00:00+00:00","source":"cache","items":[],"notes":[],"degraded":false}',
        encoding="utf-8",
    )
    monkeypatch.setattr("steelman.catalog.cache_path", lambda: cache_file)
    assert _load_cached_snapshot() is None
