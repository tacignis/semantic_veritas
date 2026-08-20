# semantic-veritas (svt)

CLI tool (`svt`) for managing semantic versioning across polyglot repositories via a
root `version.yml` file. All commands operate on the current working directory.
Supports `pyproject.toml`, `package.json`, `Cargo.toml`, and `go.mod` as version sources.
Optional git tagging and Python package-manager alignment (`uv`/`poetry`) on `bump`.

## Dev environment

```
uv sync                  # install deps + dev deps
uv run svt --help        # smoke test
uv run pytest            # run all tests
```

Python >=3.11 required. Dependency management: `uv` only (no pip). Dev deps live in
`[dependency-groups] dev` in `pyproject.toml` (not `[project.optional-dependencies]`).

## Build & test

```
uv run pytest                          # full test suite
uv run pytest tests/test_semantic_veritas.py::test_svt_init_creates_version_file
uv run svt --version                   # print tool version (uses importlib.metadata)
```

No Makefile, no CI config in this repo. Build a wheel with `uv build`.
The `tests/lab/` subdirectory contains polyglot fixture projects (python, node, rust, go)
used as on-disk test data. Don't delete or restructure them.

## Project layout

```
src/semantic_veritas/
  __init__.py           # get_tool_version() via importlib.metadata
  semantic_veritas.py   # Typer CLI commands (init, version, bump, set, reconcile)
  functions.py          # pure helper functions; no CLI coupling
  data_models.py        # Pydantic models: Project, Version
tests/
  test_semantic_veritas.py   # all tests; uses typer.testing.CliRunner
  lab/                       # polyglot fixture projects
version.yml                  # this repo's own managed version state
```

## Conventions

File header block on every source file: `# File:`, `# Author: Jonathan Belden`, `# Description:`.

Functions follow single-responsibility and build-a-result style:
- Max one `return` statement per function. Accumulate into a named `result` var, return once at the end.
- Objects (Pydantic `BaseModel`) carry state; functions handle computation.
- Errors surface as return values in `functions.py`; CLI layer catches and calls `raise typer.Exit(code=1)`.

Tests:
- Use `typer.testing.CliRunner` (not `subprocess`).
- The `project_dir` fixture does `monkeypatch.chdir(tmp_path)` — all CLI invocations read cwd.
  New tests that exercise file-touching commands must use this fixture or an equivalent chdir.
- No pytest markers or custom config; plain `pytest` collects everything.

Semver format: `X.Y.Z` or `X.Y.Z.b` (four-segment with optional build). Validated by
`SEMVER_PATTERN` in `data_models.py`. The `v` prefix is never stored, only allowed on git tags.

`version.yml` now uses a **structured VersionEntry mapping** for version fields:

```yaml
version:
  current:
    semver: '0.4.3'   # X.Y or X.Y.Z numeric core
    build: null        # optional 4th numeric segment
    tag_suffix: null   # optional alphanumeric label (e.g. rc1, 260819)
  previous:
    semver: '0.4.2'
    build: null
    tag_suffix: null
```

A **migration shim** in `Version.migrate_flat_format` auto-decomposes legacy flat strings
(`current: '0.4.2'`) and YAML floats (`current: 3.12`) on read — no manual migration needed.
Use `VersionEntry.from_string('1.2.3-rc1')` to construct a `VersionEntry` from a flat string.
Use `entry.composed()` to get the flat string back.

## Pitfalls

- Running `svt bump` in this repo will invoke `uv version <new>` to align `pyproject.toml`
  (because `version.yml` points to `pyproject.toml` and `uv.lock` is present). Use
  `--skip-sync` to bump only `version.yml`.
- `svt bump` fails with an error (not a prompt) when manifest resolution is ambiguous.
  In polyglot directories with no `manifest` key in `version.yml`, it will error out unless
  you pass `--manifest <path>` or set `manifest` in `version.yml` first.
- `version.yml` is version-controlled and is the source of truth; it is not generated.
  Prefer `svt set`, `svt bump`, or `svt reconcile` over hand-editing it.
- `dist/` contains pre-built artifacts; they are not necessarily current. Rebuild with
  `uv build` if you need a fresh wheel.
