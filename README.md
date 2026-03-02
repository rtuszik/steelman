# Steelman

## Disclaimer

This project is vibe-coded.

Assume there are bugs, rough edges, missing validation, and incorrect assumptions.
Review the output before relying on it.

`steelman` is a reporting CLI for Flux-managed Helm releases.

It scans Flux resources from:

- live Kubernetes clusters
- Git repositories containing Flux manifests
- or both

It compares those releases against Docker Hardened Images catalog data and reports one of:

- already using a DHI chart
- a DHI chart replacement is available
- DHI image replacements are available inside the chart values
- no DHI replacement was found

## Scope

Current scope:

- Flux `HelmRelease`
- Flux `HelmRepository`
- Flux `OCIRepository`

Not currently supported:

- plain Helm releases that are not represented as Flux resources
- Argo CD applications
- direct workload or pod inspection
- `valuesFrom` resolution

## What It Checks

For each Flux release, the tool:

1. identifies the current chart source
2. checks whether a DHI chart exists
3. if not, tries to resolve chart defaults with `helm show values`
4. merges inline `HelmRelease.spec.values`
5. extracts image references from the effective values
6. checks whether matching DHI images exist

Chart replacement takes precedence over image replacement.

## Requirements

- Python 3.12+
- `uv`
- `helm` if you want image replacement analysis
- kubeconfig access if you want live cluster scanning

## Usage

From the repo root:

```bash
uv run steelman
```

Common variants:

```bash
uv run steelman --mode cluster
uv run steelman --mode git --repo /path/to/gitops-repo
uv run steelman --contexts prod-eu,prod-us
uv run steelman --output-dir reports
uv run steelman --offline
uv run steelman --skip-image-analysis
uv run steelman --helm-bin helm
uv run steelman --image-match-threshold 0.75
uv run steelman --aliases ./aliases.yaml
uv run steelman --verbose
```

## Defaults

If run without flags:

- `--mode both`
- scans `.` recursively for Flux manifests
- reads kubeconfig from the default location
- uses all contexts if kubeconfig contains 10 or fewer contexts
- otherwise uses the current context only
- writes:
    - `./steelman.md`
    - `./steelman.json`

## Output

The Markdown report contains:

- summary
- already on DHI chart
- hardened chart available
- hardened images available
- no DHI replacement
- scan notes

The JSON report contains:

- catalog metadata
- inventory summary
- recommendation counts
- per-release results
- recorded errors

## Current Limitations

- `valuesFrom` is detected but not resolved
- image analysis depends on `helm show values`
- some OCI chart sources may fail `helm show values` depending on how the chart is published
- matching is heuristic and may still need alias tuning for edge cases

## Development

```bash
uv sync --group dev
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest
```
