from __future__ import annotations

from pathlib import Path

from steelman.inventory_git import scan_repo


def test_scan_repo_resolves_helm_repository(tmp_path: Path) -> None:
    manifests = tmp_path / "manifests.yaml"
    manifests.write_text(
        """
apiVersion: source.toolkit.fluxcd.io/v1
kind: HelmRepository
metadata:
  name: external-dns
  namespace: networking
spec:
  url: https://kubernetes-sigs.github.io/external-dns/
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: external-dns
  namespace: networking
spec:
  values:
    image:
      repository: ghcr.io/kubernetes-sigs/external-dns
  chart:
    spec:
      chart: external-dns
      version: 1.18.0
      sourceRef:
        kind: HelmRepository
        name: external-dns
        namespace: networking
""",
        encoding="utf-8",
    )

    items, errors = scan_repo(tmp_path)
    assert not errors
    item = items[0]
    assert item.current.source_kind == "helm"
    assert item.current.source_url == "https://kubernetes-sigs.github.io/external-dns/"
    assert item.inline_values == {"image": {"repository": "ghcr.io/kubernetes-sigs/external-dns"}}


def test_scan_repo_resolves_oci_repository_chartref(tmp_path: Path) -> None:
    manifests = tmp_path / "oci.yaml"
    manifests.write_text(
        """
apiVersion: source.toolkit.fluxcd.io/v1
kind: OCIRepository
metadata:
  name: reloader
  namespace: apps
spec:
  url: oci://ghcr.io/stakater/reloader-chart
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: reloader
  namespace: apps
spec:
  valuesFrom:
    - kind: ConfigMap
      name: reloader-values
  chartRef:
    kind: OCIRepository
    name: reloader
    namespace: apps
""",
        encoding="utf-8",
    )

    items, errors = scan_repo(tmp_path)
    assert not errors
    item = items[0]
    assert item.current.source_kind == "oci"
    assert item.current.source_url == "oci://ghcr.io/stakater/reloader-chart"
    assert item.values_from_items == [{"kind": "ConfigMap", "name": "reloader-values"}]
