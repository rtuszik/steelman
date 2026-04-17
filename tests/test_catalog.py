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
metadata:
  display-name: External DNS
  short-description: Hardened external dns chart
  featured: false
  fips-compliant: false
  fips-modules: []
  stig-certified: false
  home-url: https://kubernetes-sigs.github.io/external-dns/
  categories:
    - networking
  alternatives: []
""",
            "catalog-main/image/kyverno/info.yaml": """
metadata:
  display-name: kyverno
  short-description: Hardened kyverno image
  featured: false
  fips-compliant: false
  fips-modules: []
  stig-certified: false
  home-url: https://github.com/kyverno/kyverno
  categories:
    - security
  alternatives: []
""",
            "catalog-main/.info.spec.json": """
{
  "properties": {
    "metadata": {
      "properties": {
        "display-name": {},
        "short-description": {},
        "home-url": {}
      }
    }
  }
}
""",
        }
    )
    snapshot = parse_catalog_archive(content)
    assert len(snapshot.charts) == 1
    assert len(snapshot.images) == 1
    assert snapshot.charts[0].dhi_repo == "external-dns-chart"
    assert snapshot.charts[0].display_name == "External DNS"
    assert snapshot.charts[0].description == "Hardened external dns chart"
    assert snapshot.charts[0].home_url == "https://kubernetes-sigs.github.io/external-dns/"
    assert snapshot.images[0].image_repo == "kyverno"
    assert snapshot.images[0].home_url == "https://github.com/kyverno/kyverno"
    assert not snapshot.degraded


def test_parse_catalog_archive_marks_missing_upstream_schema_keys_as_degraded() -> None:
    content = _archive(
        {
            "catalog-main/chart/stakater-reloader/info.yaml": """
metadata:
  display-name: Reloader Helm Chart
  short-description: Watches config and secret changes
  featured: false
  fips-compliant: false
  fips-modules: []
  stig-certified: false
  home-url: https://github.com/stakater/Reloader
  categories:
    - developer-tools
  alternatives: []
""",
            "catalog-main/.info.spec.json": """
{
  "properties": {
    "metadata": {
      "properties": {
        "display-name": {},
        "short-description": {}
      }
    }
  }
}
""",
        }
    )

    snapshot = parse_catalog_archive(content)

    assert snapshot.degraded
    assert snapshot.notes is not None
    assert "home-url" in snapshot.notes[0]


def test_legacy_cache_shape_is_ignored(tmp_path, monkeypatch) -> None:
    cache_file = tmp_path / "catalog.json"
    cache_file.write_text(
        '{"fetchedAt":"2026-03-02T00:00:00+00:00","source":"cache","items":[],"notes":[],"degraded":false}',
        encoding="utf-8",
    )
    monkeypatch.setattr("steelman.catalog.cache_path", lambda: cache_file)
    assert _load_cached_snapshot() is None
