# Steelman

> [!WARNING]
> This project is vibe-coded.
> Assume there are bugs, rough edges, missing validation, and incorrect assumptions.
> Review the output before relying on it.

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

Using the published package:

```bash
uvx steelman
```

Common variants:

```bash
uvx steelman --mode cluster
uvx steelman --mode git --repo /path/to/gitops-repo
uvx steelman --contexts prod-eu,prod-us
uvx steelman --output-dir reports
uvx steelman --offline
uvx steelman --skip-image-analysis
uvx steelman --include-already-migrated
uvx steelman --helm-bin helm
uvx steelman --image-match-threshold 0.75
uvx steelman --aliases ./aliases.yaml
uvx steelman --verbose
```

## Defaults

If run without flags:

- `--mode both`
- scans `.` recursively for Flux manifests
- reads kubeconfig from the default location
- uses all contexts if kubeconfig contains 10 or fewer contexts
- otherwise uses the current context only
- omits the `already_dhi_chart` section from the Markdown report
- writes:
    - `./steelman.md`
    - `./steelman.json`

## Output

The Markdown report contains:

- summary
- hardened chart available
- hardened images available
- no DHI replacement
- scan notes

Use `--include-already-migrated` if you want the Markdown report to include releases that are already using DHI charts.

The JSON report contains:

- catalog metadata
- inventory summary
- recommendation counts
- per-release results
- recorded errors

## CI Examples

These examples assume:

- the repository is a Flux v2 GitOps repository
- the scan should use Git manifests, not live cluster access
- the generated report should be kept as an artifact or posted into an issue

For Git-only scans, use:

```bash
uvx steelman --mode git --repo . --output-dir reports
```

### GitHub Actions

This example runs on a schedule and on manual dispatch, scans the current Flux repo, uploads the report artifacts, and creates or updates an issue named `steelman report`.

```yaml
name: Steelman Report

on:
    schedule:
        - cron: "0 6 * * 1"
    workflow_dispatch:

permissions:
    contents: read
    issues: write

jobs:
    steelman:
        runs-on: ubuntu-latest
        steps:
            - name: Checkout repository
              uses: actions/checkout@v6

            - name: Set up uv
              uses: astral-sh/setup-uv@v7

            - name: Run steelman
              run: uvx steelman --mode git --repo . --output-dir reports

            - name: Upload reports
              uses: actions/upload-artifact@v6
              with:
                  name: steelman-report
                  path: reports/*
                  if-no-files-found: error

            - name: Create or update issue
              env:
                  GH_TOKEN: ${{ github.token }}
              run: |
                  issue_number="$(gh issue list --state open --label steelman --search 'steelman report in:title' --json number --jq '.[0].number')"
                  if [ -n "$issue_number" ]; then
                    gh issue edit "$issue_number" --title "steelman report" --body-file reports/steelman.md
                  else
                    gh issue create --title "steelman report" --label steelman --body-file reports/steelman.md
                  fi
```

Notes:

- this scans desired state from Git only
- `reports/steelman.md` and `reports/steelman.json` are uploaded as artifacts
- the issue update step requires `issues: write`

### Woodpecker CI

This example runs the same Git-only scan and stores the generated files in the workspace. If your Woodpecker setup exposes a GitHub token, you can also open or update an issue with `gh`.

```yaml
steps:
    steelman:
        image: ghcr.io/astral-sh/uv:python3.13-bookworm
        commands:
            - uvx steelman --mode git --repo . --output-dir reports

    steelman-report:
        image: ghcr.io/astral-sh/uv:python3.13-bookworm
        environment:
            GITHUB_TOKEN:
                from_secret: github_token
        commands:
            - apt-get update
            - apt-get install -y gh
            - issue_number="$(gh issue list --repo "$CI_REPO" --state open --label steelman --search 'steelman report in:title' --json number --jq '.[0].number')"
            - |
                if [ -n "$issue_number" ]; then
                  gh issue edit "$issue_number" --repo "$CI_REPO" --title "steelman report" --body-file reports/steelman.md
                else
                  gh issue create --repo "$CI_REPO" --title "steelman report" --label steelman --body-file reports/steelman.md
                fi
```

Notes:

- the second step is optional
- if you do not want issue creation, keep only the `steelman` step
- artifact handling in Woodpecker depends on your runner and storage configuration, so this example leaves the report in `reports/`

### GitLab CI

This example runs the same Git-only scan in a Flux repository, stores the generated reports as job artifacts, and optionally opens or updates a GitLab issue using the API.

```yaml
stages:
    - report

steelman:
    stage: report
    image: ghcr.io/astral-sh/uv:python3.13-bookworm
    script:
        - uvx steelman --mode git --repo . --output-dir reports
    artifacts:
        when: always
        paths:
            - reports/steelman.md
            - reports/steelman.json
        expire_in: 7 days

steelman_issue:
    stage: report
    image: debian:bookworm-slim
    needs:
        - job: steelman
          artifacts: true
    rules:
        - if: $GITLAB_TOKEN
    script:
        - apt-get update
        - apt-get install -y curl jq
        - |
            issue_iid="$(curl --silent --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
              "$CI_API_V4_URL/projects/$CI_PROJECT_ID/issues?state=opened&search=steelman%20report" | jq -r '.[0].iid // empty')"
        - |
            report_body="$(jq -Rs . < reports/steelman.md)"
            if [ -n "$issue_iid" ]; then
              curl --silent --request PUT \
                --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
                --header "Content-Type: application/json" \
                --data "{\"title\":\"steelman report\",\"description\":$report_body}" \
                "$CI_API_V4_URL/projects/$CI_PROJECT_ID/issues/$issue_iid"
            else
              curl --silent --request POST \
                --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
                --header "Content-Type: application/json" \
                --data "{\"title\":\"steelman report\",\"description\":$report_body,\"labels\":\"steelman\"}" \
                "$CI_API_V4_URL/projects/$CI_PROJECT_ID/issues"
            fi
```

Notes:

- the `steelman_issue` job is optional
- set `GITLAB_TOKEN` as a masked CI variable if you want issue creation
- if you only want artifacts, keep just the `steelman` job

### Cluster Mode In CI

If you want to scan live clusters instead of Git manifests, switch to:

```bash
uvx steelman --mode cluster --contexts prod-eu,prod-us --output-dir reports
```

That requires kubeconfig access in the CI environment. For a Flux repository, Git mode is usually the simpler starting point because it only scans desired state from the repo.

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
