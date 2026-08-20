# semantic-veritas

`svt` is a CLI for managing semantic versioning across polyglot repositories via a single root `version.yml` file. It keeps version state explicit, provides optional git tagging, and can align Python package managers (`uv`/`poetry`) on bump.

All commands operate on the current working directory.

```bash
pip install semantic-veritas
svt init
svt version
svt bump
```

---

## Version formats

| Format | Example | Notes |
|--------|---------|-------|
| `X.Y` | `3.13` | Two-segment; default bump increments minor |
| `X.Y-label` | `3.13-260819` | Two-segment with alphanumeric suffix |
| `X.Y.Z` | `1.2.3` | Standard semver |
| `X.Y.Z.b` | `1.2.3.4` | Semver with optional build segment |
| `X.Y.Z-label` | `1.2.3-rc1` | Any numeric format accepts a label suffix |

Labels are alphanumeric only (`[a-zA-Z0-9]+`, no dashes or dots).

---

## version.yml

```yaml
name: my-project
version:
  current:
    semver: '1.4.2'
    build: null
    tag_suffix: null
  previous:
    semver: '1.4.1'
    build: null
    tag_suffix: null
manifest: pyproject.toml   # optional
```

Legacy flat-string format (`current: '1.4.2'`) is auto-migrated on read — no manual conversion needed.

---

## Commands

### `svt init`

Creates `version.yml` in the current directory.

```bash
svt init                          # auto-discover manifest
svt init --manifest Cargo.toml    # use a specific manifest
```

Supported manifests: `pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`. When exactly one is present it is used automatically; with multiple, `svt` prompts. With none, name defaults to the directory name and version to `0.1.0`.

---

### `svt version`

Prints project version from `version.yml` (not the tool version — use `svt -V` for that).

```bash
svt version                       # my-project v1.4.2
svt version -q                    # 1.4.2
svt version -n                    # my-project
svt version -d                    # my-project/my-project:v1.4.2
svt version -p                    # 1.4.1 (previous version)
svt version --tag "GA release"    # tag + push current version
```

---

### `svt bump`

Increments `version.current` and moves the prior value to `version.previous`.

```bash
svt bump                          # patch +1 (default for X.Y.Z)
svt bump --minor                  # minor +1, patch reset
svt bump --major                  # major +1, minor/patch reset
svt bump --build                  # increment build segment
svt bump --label rc1              # append label to bumped version
svt bump --skip-sync              # skip package-manager alignment
svt bump --tag "release note"     # tag + push after bump
```

Two-segment versions (`X.Y`) default to minor bump + a YYMMDD label. Pass `--label` to override.

**Python alignment:** after a successful bump, if `pyproject.toml` is the authoritative manifest and a `uv.lock` or `poetry.lock` is present, `svt` runs `uv version <new>` or `poetry version <new>` to keep the manifest in sync. Use `--skip-sync` to bypass this. On any failure, `version.yml` is reverted and the command exits non-zero.

---

### `svt set <version>`

Sets an explicit version.

```bash
svt set 2.0.0
svt set 3.13 --label rc1         # result: 3.13-rc1
svt set 2.0.0 --tag "major GA"
```

Does not run package-manager alignment.

---

### `svt project`

Read-only inspector for `version.yml`. With no flags, prints the raw file contents.

```bash
svt project                       # raw file
svt project -q                    # name, then version (two lines)
svt project -n                    # name
svt project -v                    # current version
svt project -p                    # previous version
svt project -m                    # manifest path
svt project -n -v -p -m          # all fields, fixed order
```

---

### `svt reconcile`

Refreshes `name`, `version.current`, and `manifest` in `version.yml` from a manifest file.

```bash
svt reconcile                     # use stored or discovered manifest
svt reconcile --manifest package.json
```

If the manifest version is valid semver, `version.current` is updated and `version.previous` is cleared. If the manifest version is absent or invalid, `name` is updated but `version.current` is kept. No change writes if already aligned.

---

## Manifest resolution

On `bump` and `reconcile`, the authoritative manifest is resolved in this order:

1. `--manifest <path>` when passed explicitly
2. `manifest` key in `version.yml` when set and the file exists
3. Auto-discovery: single match → used automatically; multiple → prompt; none → fails with guidance

---

## Requirements

- Python ≥ 3.11
- Dependencies: `pydantic`, `typer`, `pyyaml`, `gitpython`

---

## License

MIT
