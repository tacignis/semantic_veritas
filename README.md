# semantic-veritas

CLI **`svt`** for reading, bumping, reconciling, and setting semver in a root **`version.yml`**, with optional git tags. All commands use the current working directory as the project root.

**Requires:** Python 3.14+ (see `pyproject.toml`). Install deps with `uv sync`. Run `uv run svt …`, or install the package so the `svt` entry point is on your `PATH`.

## `version.yml` schema

```yaml
name: project_name
version:
  current: x.y.z      # or x.y.z.b (optional fourth segment)
  previous: x.y.z     # optional; same semver forms as current
manifest: path        # optional; relative path string or null
```

| Field | Notes |
|-------|--------|
| `name` | Required. |
| `version.current` | Required. `X.Y.Z` or `X.Y.Z.b`. |
| `version.previous` | Optional. |
| `manifest` | Optional. Path written at init (relative when saved); used to resolve name/version when present. |

Invalid YAML, missing required fields, or bad semver values produce a short message and exit `1`. If `version.yml` is missing, commands print that you should run `svt init`.

## Migration from `version.txt`

Older releases used `version.txt`; **current releases only read `version.yml`.** There is no automatic migration. Replace with a `version.yml` matching the schema above, or run `svt init` (optionally `--manifest <file>`) and adjust as needed.

## Commands

### `svt init`

Creates `version.yml` in the cwd and prints `version.yml created`.

| Situation | Behavior |
|-----------|----------|
| `--manifest <path>` | Uses that file if it exists and is a supported type (`pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`). |
| No `--manifest`, 0 manifests in cwd | `name` = directory name, `version.current` = `0.1.0`. |
| No `--manifest`, exactly 1 manifest | Uses it automatically. |
| No `--manifest`, 2+ manifests | Interactive prompt to pick one. |

Name and version are taken from the manifest when possible; `go.mod` uses the module path tail for the name and may infer version from git tags.

### `svt version`

Prints a version string. With `--previous` / `-p`, uses `version.previous` (fails if unset).

| Flags | Output (non-error) |
|-------|---------------------|
| *(default)* | `{name} v{version}` |
| `-q` / `--quiet` | version only |
| `-n` / `--name-only` | name only |
| `-d` / `--docker-format` | `{name}/{name}:v{version}` |
| `-p` (and not `-q`/`-n`/`-d`) | `{version} (previous version)` |

Optional `--tag` / `-t <note>`: create and push a git tag named after the printed version; `note` is appended to the tag message. This command does not modify `version.yml`. If the tag is created locally but **push fails**, the **local tag is removed if present**; exit non-zero.

### `svt bump`

Bumps `version.current`; the old current value becomes `version.previous`.

- **Default** (no `--major` / `--minor` / `--patch` / `--build`): patch +1.
- **Exactly one** of `--major` / `-x`, `--minor` / `-y`, or `--patch` / `-z` (mutually exclusive).
- **`--build` / `-b` alone**: increment the fourth segment (or start it at `1` if absent).
- **`-b` with `-x`/`-y`/`-z`**: after the semantic bump, set the fourth segment to `0`. Without `-b`, a major/minor/patch bump **drops** an existing fourth segment.

**Package-manager alignment (Python):** By default, after `version.yml` is written, `svt` picks **uv** or **poetry** from lockfiles in the project root and runs **`uv version <semver>`** or **`poetry version <semver>`** so `pyproject.toml` matches the bump. This is not `uv sync` / `poetry install`; it is the version-setting step only.

| Lockfiles in cwd | Behavior |
|------------------|----------|
| `uv.lock` only | `uv version …` |
| `poetry.lock` only | `poetry version …` |
| Both `uv.lock` and `poetry.lock` | Fails: ambiguous; remove one lockfile or use `--skip-sync`. |
| Neither | Fails: add a lockfile or use `--skip-sync`. |

**`svt bump --skip-sync`:** Skips package-manager alignment entirely (no `uv`/`poetry` invocation).

**On alignment or config failure:** If lockfiles are ambiguous or missing, or if the `uv`/`poetry` version command fails (non-zero exit), `version.yml` is **reverted** to its pre-bump state and the command exits **non-zero**. Messages point at `--skip-sync` when skipping alignment is appropriate.

**`--tag` / `-t <note>` (optional):** After a successful bump (and alignment unless `--skip-sync`), creates the semver tag and pushes it. **Tag already exists** or **tag creation failure:** `version.yml` is reverted to the pre-bump file, exit non-zero. **Tag push failure** (after the tag was created locally): `version.yml` is reverted and the **local tag is removed if present**, exit non-zero.

### `svt set <version>`

Sets `version.current` to the argument; old current becomes `previous`. Argument must match `X.Y.Z` or `X.Y.Z.b`. **No** package-manager alignment (`uv`/`poetry` is not run). Optional `--tag` / `-t <note>`: same tag semantics as **`svt bump --tag`**—revert `version.yml` on duplicate tag, tag creation failure, or push failure; remove the local tag on push failure.

### `svt reconcile`

Refreshes **`name`**, **`version.current`**, and the **`manifest`** field in `version.yml` from a manifest file. **Direction:** the manifest is authoritative; `version.yml` is updated to match (not the other way around).

| Resolution | Behavior |
|--------------|----------|
| `--manifest <path>` | Use that file; must exist and be a supported type (`pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`). |
| No `--manifest`, `manifest` set in `version.yml` | Use the stored path (must exist and be supported). |
| No `--manifest`, no stored `manifest` | Same discovery as `svt init`: one manifest in cwd is chosen automatically; several prompt for a choice; none fails with a hint to add a manifest or run `svt init --manifest`. |

**`name`** is taken from the manifest (same rules as **`svt init`**). **`version.current`** is set from the manifest when it parses as a valid semver; otherwise the existing current value is kept.

**`version.previous`:** if **`version.current` changes** as a result of reconcile, **`previous` is cleared to `null`** (reconcile does not preserve the old bump chain when the authoritative version moves).

| Outcome | Behavior |
|---------|----------|
| Changed | Writes `version.yml` and prints `version.yml updated`. |
| No-op | Already aligned (name, current, previous, and resolved manifest path unchanged); exit `0`, no output. |
| Error | Missing/invalid `version.yml`, manifest path missing / unsupported / unresolvable, or manifest read/parse failure; short message, exit `1`. |

## Examples

```bash
uv run svt init --manifest pyproject.toml   # or: svt init …
uv run svt version                          # my-app v1.4.2
uv run svt version -q                       # 1.4.2
uv run svt version -p                       # 1.4.1 (previous version)
uv run svt bump                             # patch bump (default)
uv run svt bump --minor
uv run svt bump --skip-sync                 # bump only version.yml (no uv/poetry)
uv run svt set 2.0.0
uv run svt reconcile                        # sync from stored or discovered manifest
uv run svt reconcile --manifest package.json  # override which manifest is authoritative
```
