# semantic-veritas-tool

CLI (`svt`) for semantic versioning: read, bump, set, and optionally create git tags. Expects **`version.yml`** in the project root (current working directory).

## Breaking change: `version.txt` removed

Older releases used `version.txt`. **Current releases do not read `version.txt`.** There is no automatic migration.

**Migrate manually:** delete or ignore `version.txt`, add `version.yml` (see schema below). Either hand-write it from your old version string or run `svt init` (optionally `svt init --manifest <file>`) to create the file and pull name/version from a supported manifest when possible.

## `version.yml` schema

```yaml
name: project_name
version:
  current: x.y.z      # or x.y.z.b (optional fourth segment)
  previous: x.y.z     # optional; same semver forms as current
manifest: path        # optional; string path or null (e.g. pyproject.toml)
```

- **`name`** — project name (string).
- **`version.current`** — required; semver `X.Y.Z` or `X.Y.Z.b`.
- **`version.previous`** — optional.
- **`manifest`** — optional; path to the manifest used at init, or omitted/`null`.

## Example

```yaml
name: my-app
version:
  current: 1.4.2
  previous: 1.4.1
manifest: pyproject.toml
```

Invalid YAML or a missing `name` / `version.current` causes commands to exit with a short error (no stack trace). If `version.yml` is missing, commands tell you to run `svt init`.

## Commands

| Command | Purpose |
|--------|---------|
| `svt init` | Create `version.yml`. Optional `--manifest <path>` (`pyproject.toml`, `package.json`, `Cargo.toml`, or `go.mod`). With no manifest, uses cwd directory name and `0.1.0`; multiple manifests in cwd prompt for choice. |
| `svt version` | Print version. `--quiet` / `-q`, `--name-only` / `-n`, `--docker-format` / `-d`, `--previous` / `-p` (uses `version.previous`; non-quiet default output is `X.Y.Z (previous version)` without the project name). Optional `--tag` / `-t` (create and push git tag). |
| `svt bump` | Bump `version.current`; old value becomes `previous`. With no `--major` / `--minor` / `--patch` flags, bumps patch. Otherwise use exactly one of `--major` / `-x`, `--minor` / `-y`, or `--patch` / `-z`. `--build` / `-b` alone increments the fourth segment; with major/minor/patch it sets build to `0` on the result. Optional `--tag` / `-t`. |
| `svt set <version>` | Set `version.current` to an explicit semver. Optional `--tag` / `-t`. |

Examples:

```bash
svt init --manifest pyproject.toml
svt version              # my-app v1.4.2
svt version -q           # 1.4.2
svt version -p           # 1.4.1 (previous version)
svt bump --patch
svt set 2.0.0
```
