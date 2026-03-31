# semantic-veritas

`semantic-veritas` provides the `svt` CLI for managing project version metadata in a root `version.yml` file, with optional git tagging.

All commands run against the current working directory.

## Project Overview

`svt` helps keep project version state explicit and repeatable across polyglot repositories.

It supports:

- initializing `version.yml`
- printing current or previous project version
- bumping semantic versions (including optional build segment)
- setting an explicit version
- reconciling `version.yml` from a supported project manifest
- optionally creating and pushing git tags

`svt --version` / `svt -V` and `svt about` print the installed CLI package version.  
`svt version` prints the project version from `version.yml`.

## Key Features

- Single source of truth via root `version.yml`
- Supports `X.Y.Z` and `X.Y.Z.b` version formats
- Works with `pyproject.toml`, `package.json`, `Cargo.toml`, and `go.mod`
- Optional Python package version alignment through `uv` or `poetry` when applicable
- Safe rollback behavior on bump/tag failures

## Installation

### Requirements

- Python `3.14+` (per `pyproject.toml`)
- `uv` for dependency management in this repository

### Local Development Install

```bash
uv sync
uv run svt --help
```

You can run commands via `uv run svt ...`, or install the package so `svt` is available on your `PATH`.

## Usage

### Quick Start

```bash
uv run svt init --manifest pyproject.toml
uv run svt version
uv run svt bump
```

### `version.yml` Schema

```yaml
name: project_name
version:
  current: x.y.z      # or x.y.z.b (optional fourth segment)
  previous: x.y.z     # optional; same semver forms as current
manifest: path        # optional; relative path string or null
```

| Field | Notes |
|---|---|
| `name` | Required. |
| `version.current` | Required. `X.Y.Z` or `X.Y.Z.b`. |
| `version.previous` | Optional. |
| `manifest` | Optional. Path written at init (relative when saved); used to resolve name/version when present. |

If `version.yml` is missing, commands print guidance to run `svt init`. Invalid YAML, missing required fields, or invalid semver values return exit code `1`.

### Migration from `version.txt`

Current releases read only `version.yml`. There is no automatic migration from `version.txt`.

To migrate:

1. create `version.yml` using the schema above, or run `svt init`
2. optionally set `--manifest <file>`
3. update fields as needed

## Examples

```bash
uv run svt init --manifest pyproject.toml
uv run svt version                          # my-app v1.4.2
uv run svt version -q                       # 1.4.2
uv run svt version -p                       # 1.4.1 (previous version)
uv run svt bump                             # patch bump (default)
uv run svt bump --minor
uv run svt bump --skip-sync                 # bump only version.yml; skip package-manager alignment
uv run svt set 2.0.0
uv run svt reconcile                        # sync from stored or discovered manifest
uv run svt reconcile --manifest package.json
```

## CLI Reference

### `svt init`

Creates `version.yml` in the current directory and prints `version.yml created`.

| Situation | Behavior |
|---|---|
| `--manifest <path>` | Uses that file if it exists and is supported (`pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`). |
| No `--manifest`, 0 manifests in cwd | Sets `name` to directory name and `version.current` to `0.1.0`. |
| No `--manifest`, exactly 1 manifest | Uses it automatically. |
| No `--manifest`, 2+ manifests | Prompts interactively to choose one. |

When possible, name/version are read from the manifest. For `go.mod`, the name comes from the module path tail and version may be inferred from git tags.

### `svt version`

Prints project version data from `version.yml` (not CLI package version). With `--previous` / `-p`, uses `version.previous` and fails if it is unset.

| Flags | Output (non-error) |
|---|---|
| *(default)* | `{name} v{version}` |
| `-q`, `--quiet` | version only |
| `-n`, `--name-only` | name only |
| `-d`, `--docker-format` | `{name}/{name}:v{version}` |
| `-p` (without `-q`/`-n`/`-d`) | `{version} (previous version)` |

Optional `--tag` / `-t <note>` creates and pushes a git tag named after the printed version. The note is appended to the tag message. This command does not modify `version.yml`. If push fails after local tag creation, the local tag is removed (if present) and the command exits non-zero.

### `svt bump`

Bumps `version.current` and moves the old current value to `version.previous`.

- default (no version-part flags): patch +1
- exactly one of `--major` / `-x`, `--minor` / `-y`, `--patch` / `-z`
- `--build` / `-b` alone: increment fourth segment (or set to `1` if absent)
- `-b` with `-x`/`-y`/`-z`: apply semantic bump, then set fourth segment to `0`
- semantic bumps without `-b`: remove existing fourth segment

#### Python alignment behavior

After writing `version.yml`, `svt` may run `uv version <semver>` or `poetry version <semver>` to align `pyproject.toml`. This is version-setting only (not install/sync). Alignment runs only when the authoritative manifest for the bump is `pyproject.toml`.

Authoritative manifest resolution:

1. use `version.yml` `manifest` when set and present
2. otherwise, if exactly one supported manifest exists in cwd, use it
3. otherwise, if multiple manifests exist and both `pyproject.toml` and one Python lockfile (`uv.lock` or `poetry.lock`) are present, use `pyproject.toml`
4. otherwise, resolution fails

Lockfile behavior when `pyproject.toml` is authoritative:

| Lockfiles in cwd | Behavior |
|---|---|
| `uv.lock` only | runs `uv version ...` |
| `poetry.lock` only | runs `poetry version ...` |
| both lockfiles | fails (ambiguous); remove one or use `--skip-sync` |
| neither lockfile | fails; add a lockfile or use `--skip-sync` |

Non-Python authoritative manifests (`package.json`, `Cargo.toml`, `go.mod`) skip `uv`/`poetry` automatically.

In polyglot repos with multiple manifests and no Python lockfile, bump fails unless you disambiguate by setting `manifest` in `version.yml` (for example, `Cargo.toml`) or adding an appropriate Python lockfile for Python alignment. A lockfile without `pyproject.toml` also fails with guidance.

`svt bump --skip-sync` skips package-manager alignment for the bump, regardless of project type.

On alignment/config failure (`manifest` resolution failure, ambiguous lockfiles, missing lockfile for authoritative `pyproject.toml`, or `uv`/`poetry` version command failure), `version.yml` is reverted and the command exits non-zero.

Optional `--tag` / `-t <note>` runs after a successful bump (and alignment unless skipped). If tag creation fails, tag already exists, or push fails, `version.yml` is reverted. On push failure after local tag creation, the local tag is removed (if present).

### `svt set <version>`

Sets `version.current` to the provided version and moves the prior value to `version.previous`.

- accepted format: `X.Y.Z` or `X.Y.Z.b`
- does not run `uv`/`poetry` alignment
- optional `--tag` / `-t <note>` follows the same rollback and local-tag cleanup semantics as `svt bump --tag`

### `svt reconcile`

Refreshes `name`, `version.current`, and `manifest` in `version.yml` from a manifest. The manifest is authoritative.

| Resolution | Behavior |
|---|---|
| `--manifest <path>` | Uses that file if it exists and is supported. |
| No `--manifest`, `manifest` set in `version.yml` | Uses stored path if it exists and is supported. |
| No `--manifest`, no stored `manifest` | Same discovery as `svt init` (single auto-select, multiple prompt, none fails with guidance). |

Name is read from the manifest using the same rules as `svt init`. `version.current` is updated only if the manifest version parses as valid semver; otherwise current is kept unchanged.

If reconcile changes `version.current`, `version.previous` is cleared to `null`.

| Outcome | Behavior |
|---|---|
| Changed | Writes `version.yml` and prints `version.yml updated`. |
| No-op | Already aligned; exit `0` with no output. |
| Error | Missing/invalid `version.yml`, unsupported or missing manifest, unresolvable manifest, or manifest parse/read failure; exits `1`. |

## Development

```bash
uv sync
uv run svt --help
```

For local testing, run commands in a target project directory:

```bash
uv run svt init
uv run svt version
uv run svt bump --patch
```

## Contributing

Contributions are welcome.

When opening changes, include:

- a clear description of command behavior changes
- updated `README.md` examples/reference when CLI behavior changes
- notes about any edge-case handling (especially manifest and lockfile resolution)
