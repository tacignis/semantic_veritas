# File: tests/test_semantic_veritas.py
# Author: Jonathan Belden
# Description: Tests for the semantic-veritas-tool.

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from typer.testing import CliRunner

from semantic_veritas import get_tool_version
from semantic_veritas.data_models import Project, SEMVER_PATTERN, Version, VersionEntry
from semantic_veritas.functions import (
    detect_python_package_manager,
    parse_version_tokens,
    save_project_version,
    validate_version,
)
from semantic_veritas.semantic_veritas import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _read_version_file(project_dir: Path) -> dict:
    version_file = project_dir / "version.yml"
    content = yaml.safe_load(version_file.read_text())
    result = content if content is not None else {}
    return result


def _version_entry_composed(entry: dict | None) -> str | None:
    """Reconstruct the flat version string from a serialised VersionEntry dict.

    Handles both the new structured format (dict with semver/build/tag_suffix keys)
    and the legacy flat-string format so helpers work against both on-disk shapes.
    """
    if entry is None:
        result: str | None = None
    elif isinstance(entry, str):
        result = entry
    else:
        base = entry["semver"]
        build = entry.get("build")
        tag_suffix = entry.get("tag_suffix")
        if build is not None:
            base = f"{base}.{build}"
        if tag_suffix is not None:
            base = f"{base}-{tag_suffix}"
        result = base
    return result


def _write_version_file(
    project_dir: Path,
    name: str,
    current: str,
    previous: str | None = None,
    manifest: str | None = None,
) -> None:
    payload = {
        "name": name,
        "version": {
            "current": current,
            "previous": previous,
        },
        "manifest": manifest,
    }
    version_file = project_dir / "version.yml"
    version_file.write_text(yaml.safe_dump(payload, sort_keys=False))


def _tokenize_version(value: str) -> dict[str, int | None]:
    cleaned_value = value.strip()
    cleaned_value = cleaned_value.replace(" (previous version)", "")

    if " v" in cleaned_value:
        cleaned_value = cleaned_value.split(" v", maxsplit=1)[1]
    if "/" in cleaned_value and ":v" in cleaned_value:
        cleaned_value = cleaned_value.rsplit(":v", maxsplit=1)[1]

    parts = cleaned_value.split(".")
    return {
        "major": int(parts[0]),
        "minor": int(parts[1]),
        "patch": int(parts[2]),
        "build": int(parts[3]) if len(parts) > 3 else None,
    }


def _quiet_version(runner: CliRunner, project_dir: Path) -> str:
    result = runner.invoke(cli, ["project", "-v"], catch_exceptions=False)
    return result.output.strip()


def test_save_project_version_relative_manifest_does_not_crash(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        """[project]
name = "pkg"
version = "1.0.0"
"""
    )
    project = Project(
        name="pkg",
        version=Version(current="1.0.0", previous=None),
        manifest=Path("pyproject.toml"),
    )
    save_project_version(project, base_dir=root)
    data = yaml.safe_load((root / "version.yml").read_text())
    assert data["manifest"] == "pyproject.toml"


def test_save_project_version_absolute_manifest_inside_root_is_relative_posix(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    manifest = root / "pyproject.toml"
    manifest.write_text(
        """[project]
name = "pkg"
version = "2.0.0"
"""
    )
    project = Project(
        name="pkg",
        version=Version(current="2.0.0", previous=None),
        manifest=manifest,
    )
    save_project_version(project, base_dir=root)
    data = yaml.safe_load((root / "version.yml").read_text())
    assert data["manifest"] == "pyproject.toml"


def test_save_project_version_manifest_outside_root_stores_absolute_posix(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    manifest = outside / "pyproject.toml"
    manifest.write_text(
        """[project]
name = "pkg"
version = "3.0.0"
"""
    )
    project = Project(
        name="pkg",
        version=Version(current="3.0.0", previous=None),
        manifest=manifest,
    )
    save_project_version(project, base_dir=root)
    data = yaml.safe_load((root / "version.yml").read_text())
    assert data["manifest"] == manifest.resolve().as_posix()


def test_svt_bump_skip_sync_with_relative_manifest_in_version_yml(
    runner: CliRunner, project_dir: Path
):
    _write_version_file(
        project_dir,
        name="pkg",
        current="1.0.0",
        manifest="pyproject.toml",
    )
    (project_dir / "pyproject.toml").write_text(
        """[project]
name = "pkg"
version = "1.0.0"
"""
    )
    result = runner.invoke(cli, ["bump", "--skip-sync"], catch_exceptions=False)
    assert result.exit_code == 0
    data = _read_version_file(project_dir)
    assert data["manifest"] == "pyproject.toml"
    assert _version_entry_composed(data["version"]["current"]) == "1.0.1"


def test_svt_init_creates_version_file(runner: CliRunner, project_dir: Path):
    """
    Verifies that `svt init` does the following:
        - looks for common versioning files for common programming languages (python, javascript, rust, go, etc.)
        - sets the `project_name` variable to the name of the project if it exists, else sets it to the name of the project root directory
        - sets the `project_version` variable to the version if it exists, else sets it to 0.1.0
        - creates a version.yml file with structured version state
        - prints a message indicating the version was saved to version.yml
    """
    result = runner.invoke(cli, ["init"], catch_exceptions=False)

    assert result.exit_code == 0
    assert "version.yml created" in result.output

    data = _read_version_file(project_dir)
    assert data == {
        "name": project_dir.name,
        "version": {
            "current": {"semver": "0.1.0", "build": None, "tag_suffix": None},
            "previous": None,
        },
        "manifest": None,
    }


def test_svt_init_with_pyproject_uses_manifest_values(runner: CliRunner, project_dir: Path):
    (project_dir / "pyproject.toml").write_text(
        """[project]
name = "python-project"
version = "2.4.6"
"""
    )

    result = runner.invoke(cli, ["init"], catch_exceptions=False)

    assert result.exit_code == 0
    data = _read_version_file(project_dir)
    assert data["name"] == "python-project"
    assert _version_entry_composed(data["version"]["current"]) == "2.4.6"


def test_svt_init_with_manifest_path_uses_selected_source(runner: CliRunner, project_dir: Path):
    (project_dir / "pyproject.toml").write_text(
        """[project]
name = "python-project"
version = "1.2.3"
"""
    )
    (project_dir / "package.json").write_text('{"name":"node-project","version":"9.9.9"}')

    result = runner.invoke(
        cli,
        ["init", "--manifest", "package.json"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    data = _read_version_file(project_dir)
    assert data["name"] == "node-project"
    assert _version_entry_composed(data["version"]["current"]) == "9.9.9"


def test_svt_init_with_unknown_manifest_fails(runner: CliRunner, project_dir: Path):
    (project_dir / "other_spec.yml").write_text("name: demo\nversion: 1.2.3\n")

    result = runner.invoke(
        cli,
        ["init", "--manifest", "other_spec.yml"],
        catch_exceptions=False,
    )

    assert result.exit_code != 0
    assert "supported manifest" in result.output.lower()


def test_svt_init_corrupt_manifest_parse_fails_without_traceback(
    runner: CliRunner,
    project_dir: Path,
):
    (project_dir / "pyproject.toml").write_text("[project\nname = \"broken\"\n")

    result = runner.invoke(cli, ["init"], catch_exceptions=False)

    assert result.exit_code == 1
    combined = (result.stderr or "") + (result.stdout or "")
    assert "could not be parsed" in combined.lower()
    assert "pyproject.toml" in combined
    assert "traceback" not in combined.lower()
    assert not (project_dir / "version.yml").exists()


def test_svt_init_manifest_read_decode_fails_without_traceback(
    runner: CliRunner,
    project_dir: Path,
):
    (project_dir / "pyproject.toml").write_bytes(b"\xff\xfe\x00")

    result = runner.invoke(cli, ["init"], catch_exceptions=False)

    assert result.exit_code == 1
    combined = (result.stderr or "") + (result.stdout or "")
    assert "could not be read" in combined.lower()
    assert "pyproject.toml" in combined
    assert "traceback" not in combined.lower()
    assert not (project_dir / "version.yml").exists()


def test_svt_init_prompts_when_multiple_sources_found(runner: CliRunner, project_dir: Path):
    (project_dir / "pyproject.toml").write_text(
        """[project]
name = "python-project"
version = "1.2.3"
"""
    )
    (project_dir / "Cargo.toml").write_text(
        """[package]
name = "rust-project"
version = "3.2.1"
"""
    )

    result = runner.invoke(cli, ["init"], input="2\n", catch_exceptions=False)

    assert result.exit_code == 0
    assert "authoritative" in result.output.lower()

    data = _read_version_file(project_dir)
    assert data["name"] == "rust-project"
    assert _version_entry_composed(data["version"]["current"]) == "3.2.1"


def test_svt_init_reprompts_on_invalid_manifest_selection(runner: CliRunner, project_dir: Path):
    (project_dir / "pyproject.toml").write_text(
        """[project]
name = "python-project"
version = "1.2.3"
"""
    )
    (project_dir / "Cargo.toml").write_text(
        """[package]
name = "rust-project"
version = "3.2.1"
"""
    )

    result = runner.invoke(
        cli,
        ["init"],
        input="abc\n9\n1\n",
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert "enter a number" in result.output.lower()


def test_svt_project_missing_file_fails(runner: CliRunner, project_dir: Path):
    """
    Verifies that `svt project` exits non-zero when `version.yml` is missing.
    """
    result = runner.invoke(cli, ["project"], catch_exceptions=False)

    assert result.exit_code != 0
    assert "run `svt init`" in result.output.lower()


def test_validate_version_uses_shared_semver_rule():
    assert validate_version("1.2.3")
    assert validate_version("1.2.3.4")
    assert validate_version("  2.0.0.1  ")
    assert validate_version("1.2")          # two-segment now valid
    assert validate_version("3.13-alpine")  # two-segment with label now valid
    assert not validate_version("1")        # single segment still invalid
    assert not validate_version("v1.2.3")
    assert SEMVER_PATTERN.fullmatch("1.2.3.4")


@pytest.mark.parametrize(
    "cli_args",
    [
        ["project", "-v"],
        ["bump"],
        ["set", "1.0.0"],
        ["reconcile"],
    ],
)
def test_svt_rejects_malformed_yaml_version_file(
    runner: CliRunner,
    project_dir: Path,
    cli_args: list[str],
):
    (project_dir / "version.yml").write_text("name: [\n  bad: yaml\n")

    result = runner.invoke(cli, cli_args, catch_exceptions=False)

    assert result.exit_code == 1
    assert "could not be parsed as YAML" in result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize(
    "cli_args",
    [
        ["project", "-v"],
        ["bump"],
        ["set", "1.0.0"],
        ["reconcile"],
    ],
)
def test_svt_rejects_invalid_schema_version_file(
    runner: CliRunner,
    project_dir: Path,
    cli_args: list[str],
):
    (project_dir / "version.yml").write_text(
        yaml.safe_dump({"name": "x", "version": {"current": "not-a-version"}})
    )

    result = runner.invoke(cli, cli_args, catch_exceptions=False)

    assert result.exit_code == 1
    assert "invalid or incomplete" in result.output.lower()
    assert "Traceback" not in result.output


@pytest.mark.parametrize("tool_version_args", [["--version"], ["-V"]])
def test_svt_tool_version_flags_exit_zero(runner: CliRunner, tool_version_args: list[str]):
    expected = get_tool_version()
    result = runner.invoke(cli, tool_version_args, catch_exceptions=False)
    assert result.exit_code == 0
    assert result.output.strip() == expected


def test_svt_about_prints_tool_version_and_exits_zero(runner: CliRunner):
    expected = get_tool_version()
    result = runner.invoke(cli, ["about"], catch_exceptions=False)
    assert result.exit_code == 0
    assert result.output.strip() == expected


def test_svt_help_includes_tool_version_context(runner: CliRunner):
    tool_ver = get_tool_version()
    result = runner.invoke(cli, ["--help"], catch_exceptions=False)
    assert result.exit_code == 0
    out = result.output
    assert "Tool package" in out
    assert "semantic-veritas" in out
    assert tool_ver in out


def test_svt_project_formats(runner: CliRunner, project_dir: Path):
    _write_version_file(project_dir, name="project_name", current="0.1.0")

    # No flags: raw file contents
    raw = (project_dir / "version.yml").read_text()
    result = runner.invoke(cli, ["project"], catch_exceptions=False)
    assert result.exit_code == 0
    assert result.output == raw

    result = runner.invoke(cli, ["project", "-v"], catch_exceptions=False)
    assert result.exit_code == 0
    assert result.output.strip() == "0.1.0"

    result = runner.invoke(cli, ["project", "-n"], catch_exceptions=False)
    assert result.exit_code == 0
    assert result.output.strip() == "project_name"

    result = runner.invoke(cli, ["project", "-d"], catch_exceptions=False)
    assert result.exit_code == 0
    assert result.output.strip() == "project_name/project_name:v0.1.0"


def test_svt_project_previous_when_unset_outputs_empty(runner: CliRunner, project_dir: Path):
    _write_version_file(project_dir, name="project_name", current="0.1.0")

    result = runner.invoke(cli, ["project", "-p"], catch_exceptions=False)

    assert result.exit_code == 0
    assert result.output.strip() == ""


def test_svt_project_previous_formats(runner: CliRunner, project_dir: Path):
    _write_version_file(project_dir, name="project_name", current="1.4.2", previous="1.4.1")

    result = runner.invoke(cli, ["project", "-p"], catch_exceptions=False)
    assert result.exit_code == 0
    assert result.output.strip() == "1.4.1"


def test_svt_bump_missing_file_fails(runner: CliRunner, project_dir: Path):
    result = runner.invoke(cli, ["bump"], catch_exceptions=False)

    assert result.exit_code != 0
    assert "run `svt init`" in result.output.lower()


def _write_minimal_pyproject_with_lock(project_dir: Path) -> None:
    (project_dir / "pyproject.toml").write_text(
        """[project]
name = "project_name"
version = "1.2.3"
"""
    )
    (project_dir / "uv.lock").write_text("")


@patch("semantic_veritas.semantic_veritas.sync_python_package_version")
def test_svt_bump_default_calls_sync_helper(
    mock_sync: MagicMock,
    runner: CliRunner,
    project_dir: Path,
):
    _write_version_file(project_dir, name="project_name", current="1.2.3")
    _write_minimal_pyproject_with_lock(project_dir)

    result = runner.invoke(cli, ["bump"], catch_exceptions=False)

    assert result.exit_code == 0
    mock_sync.assert_called_once_with("1.2.4")
    assert _version_entry_composed(_read_version_file(project_dir)["version"]["current"]) == "1.2.4"


@patch("semantic_veritas.semantic_veritas.sync_python_package_version")
def test_svt_bump_sync_failure_reverts_version_yml_and_exits(
    mock_sync: MagicMock,
    runner: CliRunner,
    project_dir: Path,
):
    mock_sync.side_effect = RuntimeError("sync failed")
    _write_version_file(project_dir, name="project_name", current="1.2.3")
    _write_minimal_pyproject_with_lock(project_dir)

    result = runner.invoke(cli, ["bump"], catch_exceptions=False)

    assert result.exit_code == 1
    mock_sync.assert_called_once_with("1.2.4")
    assert _version_entry_composed(_read_version_file(project_dir)["version"]["current"]) == "1.2.3"
    assert _version_entry_composed(_read_version_file(project_dir)["version"]["previous"]) is None
    combined = (result.stderr or "") + (result.stdout or "")
    assert "--skip-sync" in combined
    assert "reverted" in combined.lower()


@patch("semantic_veritas.semantic_veritas.sync_python_package_version")
def test_svt_bump_cargo_only_skips_python_sync(
    mock_sync: MagicMock,
    runner: CliRunner,
    project_dir: Path,
):
    (project_dir / "Cargo.toml").write_text(
        """[package]
name = "rust-project"
version = "1.2.3"
"""
    )
    _write_version_file(project_dir, name="rust-project", current="1.2.3")

    result = runner.invoke(cli, ["bump"], catch_exceptions=False)

    assert result.exit_code == 0
    mock_sync.assert_not_called()
    assert _version_entry_composed(_read_version_file(project_dir)["version"]["current"]) == "1.2.4"


@patch("semantic_veritas.semantic_veritas.sync_python_package_version")
def test_svt_bump_version_yml_cargo_manifest_skips_python_sync_when_pyproject_exists(
    mock_sync: MagicMock,
    runner: CliRunner,
    project_dir: Path,
):
    (project_dir / "Cargo.toml").write_text(
        """[package]
name = "rust-project"
version = "1.2.3"
"""
    )
    (project_dir / "pyproject.toml").write_text(
        """[project]
name = "pkg"
version = "1.2.3"
"""
    )
    _write_version_file(project_dir, name="rust-project", current="1.2.3", manifest="Cargo.toml")

    result = runner.invoke(cli, ["bump"], catch_exceptions=False)

    assert result.exit_code == 0
    mock_sync.assert_not_called()
    assert _version_entry_composed(_read_version_file(project_dir)["version"]["current"]) == "1.2.4"


def test_svt_bump_stored_manifest_missing_fails_with_guidance_and_reverts(
    runner: CliRunner,
    project_dir: Path,
):
    _write_version_file(project_dir, name="pkg", current="1.2.3", manifest="Cargo.toml")

    result = runner.invoke(cli, ["bump"], catch_exceptions=False)

    assert result.exit_code == 1
    assert _version_entry_composed(_read_version_file(project_dir)["version"]["current"]) == "1.2.3"
    combined = (result.stderr or "") + (result.stdout or "")
    assert "stored manifest" in combined.lower()
    assert "does not exist" in combined.lower()
    assert "reverted" in combined.lower()


def test_svt_bump_both_locks_with_pyproject_authoritative_fails_and_reverts(
    runner: CliRunner,
    project_dir: Path,
):
    (project_dir / "pyproject.toml").write_text(
        """[project]
name = "pkg"
version = "1.2.3"
"""
    )
    (project_dir / "uv.lock").write_text("")
    (project_dir / "poetry.lock").write_text("")
    _write_version_file(project_dir, name="pkg", current="1.2.3", manifest="pyproject.toml")

    result = runner.invoke(cli, ["bump"], catch_exceptions=False)

    assert result.exit_code == 1
    assert _version_entry_composed(_read_version_file(project_dir)["version"]["current"]) == "1.2.3"
    combined = (result.stderr or "") + (result.stdout or "")
    assert "Both poetry.lock and uv.lock" in combined
    assert "reverted" in combined.lower()


def test_svt_bump_lock_without_pyproject_polyglot_fails_with_guidance(
    runner: CliRunner,
    project_dir: Path,
):
    (project_dir / "Cargo.toml").write_text(
        """[package]
name = "rust-project"
version = "1.2.3"
"""
    )
    (project_dir / "package.json").write_text('{"name":"node","version":"1.0.0"}')
    (project_dir / "uv.lock").write_text("")
    _write_version_file(project_dir, name="rust-project", current="1.2.3", manifest=None)

    result = runner.invoke(cli, ["bump"], catch_exceptions=False)

    assert result.exit_code == 1
    assert _version_entry_composed(_read_version_file(project_dir)["version"]["current"]) == "1.2.3"
    combined = (result.stderr or "") + (result.stdout or "")
    assert "pyproject.toml" in combined.lower()
    assert "poetry.lock" in combined.lower() or "uv.lock" in combined.lower()
    assert "reverted" in combined.lower()


@patch("semantic_veritas.semantic_veritas.sync_python_package_version")
def test_svt_bump_polyglot_pyproject_and_lock_runs_sync(
    mock_sync: MagicMock,
    runner: CliRunner,
    project_dir: Path,
):
    (project_dir / "pyproject.toml").write_text(
        """[project]
name = "pkg"
version = "1.2.3"
"""
    )
    (project_dir / "Cargo.toml").write_text(
        """[package]
name = "rust-project"
version = "3.2.1"
"""
    )
    (project_dir / "uv.lock").write_text("")
    _write_version_file(project_dir, name="pkg", current="1.2.3", manifest=None)

    result = runner.invoke(cli, ["bump"], catch_exceptions=False)

    assert result.exit_code == 0
    mock_sync.assert_called_once_with("1.2.4")


@patch("semantic_veritas.semantic_veritas.sync_python_package_version")
def test_svt_bump_go_mod_only_skips_python_sync(
    mock_sync: MagicMock,
    runner: CliRunner,
    project_dir: Path,
):
    (project_dir / "go.mod").write_text("module example.com/foo\n\ngo 1.21\n")
    _write_version_file(project_dir, name="foo", current="1.2.3")

    result = runner.invoke(cli, ["bump"], catch_exceptions=False)

    assert result.exit_code == 0
    mock_sync.assert_not_called()
    assert _version_entry_composed(_read_version_file(project_dir)["version"]["current"]) == "1.2.4"


@patch("semantic_veritas.semantic_veritas.sync_python_package_version")
def test_svt_bump_package_json_only_skips_python_sync(
    mock_sync: MagicMock,
    runner: CliRunner,
    project_dir: Path,
):
    (project_dir / "package.json").write_text('{"name":"node-project","version":"1.2.3"}')
    _write_version_file(project_dir, name="node-project", current="1.2.3")

    result = runner.invoke(cli, ["bump"], catch_exceptions=False)

    assert result.exit_code == 0
    mock_sync.assert_not_called()
    assert _version_entry_composed(_read_version_file(project_dir)["version"]["current"]) == "1.2.4"


def test_svt_bump_pyproject_authoritative_no_lock_fails_with_guidance(
    runner: CliRunner,
    project_dir: Path,
):
    (project_dir / "pyproject.toml").write_text(
        """[project]
name = "pkg"
version = "1.2.3"
"""
    )
    _write_version_file(project_dir, name="pkg", current="1.2.3")

    result = runner.invoke(cli, ["bump"], catch_exceptions=False)

    assert result.exit_code == 1
    assert _version_entry_composed(_read_version_file(project_dir)["version"]["current"]) == "1.2.3"
    combined = (result.stderr or "") + (result.stdout or "")
    assert "pyproject.toml is authoritative" in combined
    assert "poetry.lock" in combined and "uv.lock" in combined
    assert "--skip-sync" in combined


def test_svt_bump_polyglot_no_lock_without_manifest_fails_with_actionable_message(
    runner: CliRunner,
    project_dir: Path,
):
    (project_dir / "pyproject.toml").write_text(
        """[project]
name = "python-project"
version = "1.2.3"
"""
    )
    (project_dir / "Cargo.toml").write_text(
        """[package]
name = "rust-project"
version = "3.2.1"
"""
    )
    _write_version_file(project_dir, name="python-project", current="1.2.3")

    result = runner.invoke(cli, ["bump"], catch_exceptions=False)

    assert result.exit_code == 1
    assert _version_entry_composed(_read_version_file(project_dir)["version"]["current"]) == "1.2.3"
    combined = (result.stderr or "") + (result.stdout or "")
    assert "Multiple manifests" in combined
    assert "manifest key" in combined.lower() or "version.yml" in combined
    assert "poetry.lock" in combined or "uv.lock" in combined


@patch("semantic_veritas.semantic_veritas.sync_python_package_version")
def test_svt_bump_poetry_lock_invokes_sync_path(
    mock_sync: MagicMock,
    runner: CliRunner,
    project_dir: Path,
):
    (project_dir / "pyproject.toml").write_text(
        """[project]
name = "project_name"
version = "1.2.3"
"""
    )
    (project_dir / "poetry.lock").write_text("")
    _write_version_file(project_dir, name="project_name", current="1.2.3")

    result = runner.invoke(cli, ["bump"], catch_exceptions=False)

    assert result.exit_code == 0
    mock_sync.assert_called_once_with("1.2.4")


@patch("semantic_veritas.semantic_veritas.sync_python_package_version")
def test_svt_bump_skip_sync_does_not_call_sync_helper(
    mock_sync: MagicMock,
    runner: CliRunner,
    project_dir: Path,
):
    _write_version_file(project_dir, name="project_name", current="1.2.3")

    result = runner.invoke(cli, ["bump", "--skip-sync"], catch_exceptions=False)

    assert result.exit_code == 0
    mock_sync.assert_not_called()


@patch("semantic_veritas.semantic_veritas.sync_python_package_version")
@patch("semantic_veritas.semantic_veritas.create_git_tag")
@patch("semantic_veritas.semantic_veritas.push_git_tag")
@patch("semantic_veritas.semantic_veritas.delete_local_git_tag")
def test_svt_bump_tag_push_failure_reverts_version_and_deletes_local_tag(
    mock_delete_local: MagicMock,
    mock_push: MagicMock,
    mock_create: MagicMock,
    mock_sync: MagicMock,
    runner: CliRunner,
    project_dir: Path,
):
    _write_version_file(project_dir, name="project_name", current="1.2.3")
    mock_push.side_effect = RuntimeError("tag push failed")

    result = runner.invoke(
        cli,
        ["bump", "--skip-sync", "--tag", "release"],
        catch_exceptions=False,
    )

    assert result.exit_code == 1
    mock_create.assert_called_once()
    mock_push.assert_called_once_with("1.2.4")
    mock_delete_local.assert_called_once_with("1.2.4")
    mock_sync.assert_not_called()
    assert _version_entry_composed(_read_version_file(project_dir)["version"]["current"]) == "1.2.3"
    assert _version_entry_composed(_read_version_file(project_dir)["version"]["previous"]) is None
    combined = (result.stderr or "") + (result.stdout or "")
    assert "reverted" in combined.lower()
    assert "local tag" in combined.lower()


@patch("semantic_veritas.semantic_veritas.sync_python_package_version")
@patch("semantic_veritas.semantic_veritas.push_git_tag")
@patch("semantic_veritas.semantic_veritas.create_git_tag")
def test_svt_bump_with_tag_calls_create_and_push_helpers(
    mock_create: MagicMock,
    mock_push: MagicMock,
    mock_sync: MagicMock,
    runner: CliRunner,
    project_dir: Path,
):
    _write_version_file(project_dir, name="project_name", current="1.2.3")

    result = runner.invoke(
        cli,
        ["bump", "--skip-sync", "--tag", "release"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    mock_create.assert_called_once()
    assert mock_create.call_args[0][0] == "1.2.4"
    mock_push.assert_called_once_with("1.2.4")
    mock_sync.assert_not_called()
    assert "Tag created and pushed" in result.output


@patch("semantic_veritas.semantic_veritas.push_git_tag")
@patch("semantic_veritas.semantic_veritas.create_git_tag")
def test_svt_project_with_tag_calls_create_and_push_helpers(
    mock_create: MagicMock,
    mock_push: MagicMock,
    runner: CliRunner,
    project_dir: Path,
):
    _write_version_file(project_dir, name="project_name", current="1.2.3")

    result = runner.invoke(
        cli,
        ["project", "--tag", "note"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    mock_create.assert_called_once()
    assert mock_create.call_args[0][0] == "1.2.3"
    mock_push.assert_called_once_with("1.2.3")
    assert "Tag created and pushed" in result.output


@patch("semantic_veritas.semantic_veritas.push_git_tag")
@patch("semantic_veritas.semantic_veritas.create_git_tag")
def test_svt_set_with_tag_calls_create_and_push_helpers(
    mock_create: MagicMock,
    mock_push: MagicMock,
    runner: CliRunner,
    project_dir: Path,
):
    _write_version_file(project_dir, name="project_name", current="1.2.3")

    result = runner.invoke(
        cli,
        ["set", "2.0.0", "--tag", "ga"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    mock_create.assert_called_once()
    assert mock_create.call_args[0][0] == "2.0.0"
    mock_push.assert_called_once_with("2.0.0")
    assert "Tag created and pushed" in result.output


def test_detect_python_package_manager_uv_lock_only(tmp_path: Path):
    (tmp_path / "uv.lock").write_text("")
    result = detect_python_package_manager(tmp_path)
    assert result == "uv"


def test_detect_python_package_manager_poetry_lock_only(tmp_path: Path):
    (tmp_path / "poetry.lock").write_text("")
    result = detect_python_package_manager(tmp_path)
    assert result == "poetry"


def test_detect_python_package_manager_both_locks_raises(tmp_path: Path):
    (tmp_path / "uv.lock").write_text("")
    (tmp_path / "poetry.lock").write_text("")
    with pytest.raises(ValueError, match="Both poetry.lock and uv.lock"):
        detect_python_package_manager(tmp_path)


def test_detect_python_package_manager_no_lock_raises(tmp_path: Path):
    with pytest.raises(ValueError, match="No poetry.lock or uv.lock"):
        detect_python_package_manager(tmp_path)


def test_svt_bump_default(runner: CliRunner, project_dir: Path):
    _write_version_file(project_dir, name="project_name", current="1.2.3")
    old_version = _tokenize_version(_quiet_version(runner, project_dir))

    result = runner.invoke(cli, ["bump", "--skip-sync"], catch_exceptions=False)

    assert result.exit_code == 0
    new_version = _tokenize_version(_quiet_version(runner, project_dir))
    assert new_version["major"] == old_version["major"]
    assert new_version["minor"] == old_version["minor"]
    assert new_version["patch"] == old_version["patch"] + 1
    assert new_version["build"] is None
    assert _version_entry_composed(_read_version_file(project_dir)["version"]["previous"]) == "1.2.3"


def test_svt_bump_major(runner: CliRunner, project_dir: Path):
    _write_version_file(project_dir, name="project_name", current="1.2.3")
    old_version = _tokenize_version(_quiet_version(runner, project_dir))

    result = runner.invoke(cli, ["bump", "--major", "--skip-sync"], catch_exceptions=False)

    assert result.exit_code == 0
    new_version = _tokenize_version(_quiet_version(runner, project_dir))
    assert new_version["major"] == old_version["major"] + 1
    assert new_version["minor"] == 0
    assert new_version["patch"] == 0
    assert new_version["build"] is None


def test_svt_bump_minor(runner: CliRunner, project_dir: Path):
    _write_version_file(project_dir, name="project_name", current="1.2.3")
    old_version = _tokenize_version(_quiet_version(runner, project_dir))

    result = runner.invoke(cli, ["bump", "--minor", "--skip-sync"], catch_exceptions=False)

    assert result.exit_code == 0
    new_version = _tokenize_version(_quiet_version(runner, project_dir))
    assert new_version["major"] == old_version["major"]
    assert new_version["minor"] == old_version["minor"] + 1
    assert new_version["patch"] == 0
    assert new_version["build"] is None


def test_svt_bump_patch(runner: CliRunner, project_dir: Path):
    _write_version_file(project_dir, name="project_name", current="1.2.3")
    old_version = _tokenize_version(_quiet_version(runner, project_dir))

    result = runner.invoke(cli, ["bump", "--patch", "--skip-sync"], catch_exceptions=False)

    assert result.exit_code == 0
    new_version = _tokenize_version(_quiet_version(runner, project_dir))
    assert new_version["major"] == old_version["major"]
    assert new_version["minor"] == old_version["minor"]
    assert new_version["patch"] == old_version["patch"] + 1
    assert new_version["build"] is None


def test_svt_bump_build_from_implicit_zero(runner: CliRunner, project_dir: Path):
    _write_version_file(project_dir, name="project_name", current="1.2.3")

    result = runner.invoke(cli, ["bump", "--build", "--skip-sync"], catch_exceptions=False)

    assert result.exit_code == 0
    new_version = _tokenize_version(_quiet_version(runner, project_dir))
    assert new_version == {"major": 1, "minor": 2, "patch": 3, "build": 1}


def test_svt_bump_build_major(runner: CliRunner, project_dir: Path):
    _write_version_file(project_dir, name="project_name", current="1.2.3.9")

    result = runner.invoke(cli, ["bump", "--build", "--major", "--skip-sync"], catch_exceptions=False)

    assert result.exit_code == 0
    new_version = _tokenize_version(_quiet_version(runner, project_dir))
    assert new_version == {"major": 2, "minor": 0, "patch": 0, "build": 0}


def test_svt_bump_build_minor(runner: CliRunner, project_dir: Path):
    _write_version_file(project_dir, name="project_name", current="1.2.3.9")

    result = runner.invoke(cli, ["bump", "--build", "--minor", "--skip-sync"], catch_exceptions=False)

    assert result.exit_code == 0
    new_version = _tokenize_version(_quiet_version(runner, project_dir))
    assert new_version == {"major": 1, "minor": 3, "patch": 0, "build": 0}


def test_svt_bump_build_patch(runner: CliRunner, project_dir: Path):
    _write_version_file(project_dir, name="project_name", current="1.2.3.9")

    result = runner.invoke(cli, ["bump", "--build", "--patch", "--skip-sync"], catch_exceptions=False)

    assert result.exit_code == 0
    new_version = _tokenize_version(_quiet_version(runner, project_dir))
    assert new_version == {"major": 1, "minor": 2, "patch": 4, "build": 0}


def test_svt_set_missing_file_fails(runner: CliRunner, project_dir: Path):
    result = runner.invoke(cli, ["set", "1.2.3"], catch_exceptions=False)

    assert result.exit_code != 0
    assert "run `svt init`" in result.output.lower()


def test_svt_set_explicit_version(runner: CliRunner, project_dir: Path):
    """
    Verifies that `svt set <version>` validates and saves a new version,
    while preserving previous version state.
    """
    _write_version_file(project_dir, name="project_name", current="0.1.0")

    old_version = _tokenize_version(_quiet_version(runner, project_dir))

    result = runner.invoke(cli, ["set", "1.2.3"], catch_exceptions=False)

    assert result.exit_code == 0

    new_version = _tokenize_version(_quiet_version(runner, project_dir))
    assert new_version == {"major": 1, "minor": 2, "patch": 3, "build": None}

    previous_result = runner.invoke(cli, ["project", "-p"], catch_exceptions=False)
    previous_version = _tokenize_version(previous_result.output)
    assert previous_version == old_version


def test_svt_set_rejects_invalid_version_format(runner: CliRunner, project_dir: Path):
    _write_version_file(project_dir, name="project_name", current="0.1.0")

    result = runner.invoke(cli, ["set", "1"], catch_exceptions=False)

    assert result.exit_code != 0
    assert "correct format" in result.output.lower()


def test_svt_init_multiple_sources_prefers_explicit_manifest_without_prompt(
    runner: CliRunner,
    project_dir: Path,
):
    (project_dir / "pyproject.toml").write_text(
        """[project]
name = "python-project"
version = "1.2.3"
"""
    )
    (project_dir / "Cargo.toml").write_text(
        """[package]
name = "rust-project"
version = "3.2.1"
"""
    )

    result = runner.invoke(
        cli,
        ["init", "--manifest", "pyproject.toml"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert "authoritative" not in result.output.lower()


def test_svt_init_single_source_does_not_prompt(runner: CliRunner, project_dir: Path):
    (project_dir / "package.json").write_text('{"name":"node-project","version":"4.5.6"}')

    result = runner.invoke(cli, ["init"], catch_exceptions=False)

    assert result.exit_code == 0
    assert "authoritative" not in result.output.lower()


def test_svt_reconcile_missing_file_fails(runner: CliRunner, project_dir: Path):
    result = runner.invoke(cli, ["reconcile"], catch_exceptions=False)

    assert result.exit_code != 0
    assert "run `svt init`" in result.output.lower()


def test_svt_reconcile_updates_stale_name_and_current_from_pyproject(
    runner: CliRunner,
    project_dir: Path,
):
    (project_dir / "pyproject.toml").write_text(
        """[project]
name = "python-project"
version = "2.4.6"
"""
    )
    _write_version_file(
        project_dir,
        name="stale-name",
        current="1.0.0",
        manifest="pyproject.toml",
    )

    result = runner.invoke(cli, ["reconcile"], catch_exceptions=False)

    assert result.exit_code == 0
    assert "version.yml updated" in result.output
    data = _read_version_file(project_dir)
    assert data["name"] == "python-project"
    assert _version_entry_composed(data["version"]["current"]) == "2.4.6"


def test_svt_reconcile_invalid_manifest_semver_updates_name_keeps_current_and_previous(
    runner: CliRunner,
    project_dir: Path,
):
    (project_dir / "pyproject.toml").write_text(
        """[project]
name = "python-project"
version = "not-a-valid-semver"
"""
    )
    _write_version_file(
        project_dir,
        name="stale-name",
        current="1.2.3",
        previous="0.9.0",
        manifest="pyproject.toml",
    )

    result = runner.invoke(cli, ["reconcile"], catch_exceptions=False)

    assert result.exit_code == 0
    assert "version.yml updated" in result.output
    data = _read_version_file(project_dir)
    assert data["name"] == "python-project"
    assert _version_entry_composed(data["version"]["current"]) == "1.2.3"
    assert _version_entry_composed(data["version"]["previous"]) == "0.9.0"


def test_svt_reconcile_corrupt_manifest_parse_fails_without_traceback(
    runner: CliRunner,
    project_dir: Path,
):
    (project_dir / "pyproject.toml").write_text("[project\nname = \"broken\"\n")
    _write_version_file(
        project_dir,
        name="x",
        current="1.0.0",
        manifest="pyproject.toml",
    )

    result = runner.invoke(cli, ["reconcile"], catch_exceptions=False)

    assert result.exit_code == 1
    combined = (result.stderr or "") + (result.stdout or "")
    assert "could not be parsed" in combined.lower()
    assert "pyproject.toml" in combined
    assert "traceback" not in combined.lower()


def test_svt_reconcile_manifest_read_decode_fails_without_traceback(
    runner: CliRunner,
    project_dir: Path,
):
    (project_dir / "pyproject.toml").write_bytes(b"\xff\xfe\x00")
    _write_version_file(
        project_dir,
        name="x",
        current="1.0.0",
        manifest="pyproject.toml",
    )

    result = runner.invoke(cli, ["reconcile"], catch_exceptions=False)

    assert result.exit_code == 1
    combined = (result.stderr or "") + (result.stdout or "")
    assert "could not be read" in combined.lower()
    assert "pyproject.toml" in combined
    assert "traceback" not in combined.lower()


def test_svt_reconcile_manifest_read_oserror_fails_without_traceback(
    runner: CliRunner,
    project_dir: Path,
):
    (project_dir / "pyproject.toml").write_text(
        """[project]
name = "python-project"
version = "1.0.0"
"""
    )
    _write_version_file(
        project_dir,
        name="x",
        current="1.0.0",
        manifest="pyproject.toml",
    )

    with patch(
        "semantic_veritas.semantic_veritas.parse_manifest",
        side_effect=PermissionError("denied"),
    ):
        result = runner.invoke(cli, ["reconcile"], catch_exceptions=False)

    assert result.exit_code == 1
    combined = (result.stderr or "") + (result.stdout or "")
    assert "could not be read" in combined.lower()
    assert "traceback" not in combined.lower()


def test_svt_reconcile_no_op_when_already_aligned(runner: CliRunner, project_dir: Path):
    (project_dir / "pyproject.toml").write_text(
        """[project]
name = "python-project"
version = "2.4.6"
"""
    )
    _write_version_file(
        project_dir,
        name="python-project",
        current="2.4.6",
        manifest="pyproject.toml",
    )

    before = (project_dir / "version.yml").read_text()
    result = runner.invoke(cli, ["reconcile"], catch_exceptions=False)

    assert result.exit_code == 0
    assert "version.yml updated" not in result.output
    assert (project_dir / "version.yml").read_text() == before


def test_svt_reconcile_manifest_override_uses_selected_source(
    runner: CliRunner,
    project_dir: Path,
):
    (project_dir / "pyproject.toml").write_text(
        """[project]
name = "python-project"
version = "1.0.0"
"""
    )
    (project_dir / "package.json").write_text('{"name":"node-project","version":"9.9.9"}')
    _write_version_file(
        project_dir,
        name="python-project",
        current="1.0.0",
        manifest="pyproject.toml",
    )

    result = runner.invoke(
        cli,
        ["reconcile", "--manifest", "package.json"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert "version.yml updated" in result.output
    data = _read_version_file(project_dir)
    assert data["name"] == "node-project"
    assert _version_entry_composed(data["version"]["current"]) == "9.9.9"
    assert data["manifest"] == "package.json"


def test_svt_reconcile_stored_manifest_path_missing_fails(
    runner: CliRunner,
    project_dir: Path,
):
    (project_dir / "pyproject.toml").write_text(
        """[project]
name = "python-project"
version = "1.0.0"
"""
    )
    _write_version_file(
        project_dir,
        name="python-project",
        current="1.0.0",
        manifest="missing.toml",
    )

    result = runner.invoke(cli, ["reconcile"], catch_exceptions=False)

    assert result.exit_code == 1
    combined = (result.stderr or "") + (result.stdout or "")
    assert "does not exist" in combined.lower()
    assert "stored manifest" in combined.lower()


def test_svt_reconcile_stored_manifest_unsupported_type_fails(
    runner: CliRunner,
    project_dir: Path,
):
    (project_dir / "other.toml").write_text("[meta]\nname = 'x'\n")
    _write_version_file(
        project_dir,
        name="x",
        current="1.0.0",
        manifest="other.toml",
    )

    result = runner.invoke(cli, ["reconcile"], catch_exceptions=False)

    assert result.exit_code == 1
    combined = (result.stderr or "") + (result.stdout or "")
    assert "not a supported type" in combined.lower()


def test_svt_reconcile_manifest_option_path_missing_fails(
    runner: CliRunner,
    project_dir: Path,
):
    (project_dir / "pyproject.toml").write_text(
        """[project]
name = "python-project"
version = "1.0.0"
"""
    )
    _write_version_file(
        project_dir,
        name="python-project",
        current="1.0.0",
        manifest="pyproject.toml",
    )

    result = runner.invoke(
        cli,
        ["reconcile", "--manifest", "nowhere.json"],
        catch_exceptions=False,
    )

    assert result.exit_code == 1
    combined = (result.stderr or "") + (result.stdout or "")
    assert "does not exist" in combined.lower()


def test_svt_reconcile_manifest_option_unsupported_type_fails(
    runner: CliRunner,
    project_dir: Path,
):
    (project_dir / "notes.txt").write_text("hello")
    _write_version_file(
        project_dir,
        name="project_name",
        current="1.0.0",
        manifest=None,
    )

    result = runner.invoke(
        cli,
        ["reconcile", "--manifest", "notes.txt"],
        catch_exceptions=False,
    )

    assert result.exit_code == 1
    combined = (result.stderr or "") + (result.stdout or "")
    assert "unsupported manifest type" in combined.lower()


def test_svt_reconcile_discovery_single_manifest_without_stored_key(
    runner: CliRunner,
    project_dir: Path,
):
    (project_dir / "pyproject.toml").write_text(
        """[project]
name = "python-project"
version = "2.4.6"
"""
    )
    _write_version_file(
        project_dir,
        name="stale-name",
        current="0.1.0",
        manifest=None,
    )

    result = runner.invoke(cli, ["reconcile"], catch_exceptions=False)

    assert result.exit_code == 0
    assert "version.yml updated" in result.output
    data = _read_version_file(project_dir)
    assert data["name"] == "python-project"
    assert _version_entry_composed(data["version"]["current"]) == "2.4.6"
    assert data["manifest"] == "pyproject.toml"


def test_svt_reconcile_discovery_prompts_when_multiple_manifests(
    runner: CliRunner,
    project_dir: Path,
):
    (project_dir / "pyproject.toml").write_text(
        """[project]
name = "python-project"
version = "1.2.3"
"""
    )
    (project_dir / "Cargo.toml").write_text(
        """[package]
name = "rust-project"
version = "3.2.1"
"""
    )
    _write_version_file(
        project_dir,
        name="x",
        current="0.1.0",
        manifest=None,
    )

    result = runner.invoke(cli, ["reconcile"], input="2\n", catch_exceptions=False)

    assert result.exit_code == 0
    assert "authoritative" in result.output.lower()
    data = _read_version_file(project_dir)
    assert data["name"] == "rust-project"
    assert _version_entry_composed(data["version"]["current"]) == "3.2.1"
    assert data["manifest"] == "Cargo.toml"


def test_svt_reconcile_clears_previous_when_current_changes_from_manifest(
    runner: CliRunner,
    project_dir: Path,
):
    (project_dir / "pyproject.toml").write_text(
        """[project]
name = "python-project"
version = "3.0.0"
"""
    )
    _write_version_file(
        project_dir,
        name="python-project",
        current="1.0.0",
        previous="0.9.0",
        manifest="pyproject.toml",
    )

    result = runner.invoke(cli, ["reconcile"], catch_exceptions=False)

    assert result.exit_code == 0
    data = _read_version_file(project_dir)
    assert _version_entry_composed(data["version"]["current"]) == "3.0.0"
    assert _version_entry_composed(data["version"]["previous"]) is None


# ─── Two-segment version support ─────────────────────────────────────────────


class TestTwoSegmentDataModels:
    """Version model accepts two-segment formats; rejects invalid ones."""

    def test_version_model_accepts_two_segment_numeric(self):
        v = Version(current="3.13")
        assert v.current.composed() == "3.13"

    def test_version_model_accepts_two_segment_with_numeric_label(self):
        v = Version(current="3.13-260819")
        assert v.current.composed() == "3.13-260819"

    def test_version_model_accepts_two_segment_with_alpha_label(self):
        v = Version(current="3.13-alpine")
        assert v.current.composed() == "3.13-alpine"

    def test_version_model_accepts_two_segment_with_alphanumeric_label(self):
        v = Version(current="1.0-rc1")
        assert v.current.composed() == "1.0-rc1"

    def test_version_model_rejects_double_dash_label(self):
        with pytest.raises(Exception):
            Version(current="3.13-bad-label")

    def test_version_model_rejects_single_segment(self):
        with pytest.raises(Exception):
            Version(current="3")

    def test_version_model_accepts_two_segment_previous(self):
        v = Version(current="3.14", previous="3.13")
        assert v.previous.composed() == "3.13"


class TestTwoSegmentValidateVersion:
    """validate_version() returns True for new formats."""

    def test_validate_version_two_segment_numeric(self):
        assert validate_version("3.13") is True

    def test_validate_version_two_segment_with_label(self):
        assert validate_version("3.13-260819") is True

    def test_validate_version_two_segment_with_alpha_label(self):
        assert validate_version("3.13-alpine") is True

    def test_validate_version_single_segment_still_invalid(self):
        assert validate_version("3") is False

    def test_validate_version_double_dash_still_invalid(self):
        assert validate_version("3.13-bad-label") is False


class TestParseVersionTokensTwoSegment:
    """parse_version_tokens handles 2-segment formats correctly."""

    def test_parse_two_segment_plain(self):
        tokens = parse_version_tokens("3.13")
        assert tokens["major"] == 3
        assert tokens["minor"] == 13
        assert tokens["patch"] is None
        assert tokens["build"] is None
        assert tokens["label"] is None

    def test_parse_two_segment_with_label(self):
        tokens = parse_version_tokens("3.13-260819")
        assert tokens["major"] == 3
        assert tokens["minor"] == 13
        assert tokens["patch"] is None
        assert tokens["label"] == "260819"

    def test_parse_three_segment_with_label(self):
        tokens = parse_version_tokens("1.2.3-rc1")
        assert tokens["major"] == 1
        assert tokens["minor"] == 2
        assert tokens["patch"] == 3
        assert tokens["label"] == "rc1"

    def test_parse_three_segment_without_label(self):
        tokens = parse_version_tokens("1.2.3")
        assert tokens["label"] is None


class TestSvtSetTwoSegment:
    """svt set accepts two-segment versions and stores them correctly."""

    def test_set_two_segment_numeric(self, runner: CliRunner, project_dir: Path):
        _write_version_file(project_dir, name="project_name", current="1.0.0")
        result = runner.invoke(cli, ["set", "3.13"], catch_exceptions=False)
        assert result.exit_code == 0
        data = _read_version_file(project_dir)
        assert _version_entry_composed(data["version"]["current"]) == "3.13"

    def test_set_two_segment_with_label(self, runner: CliRunner, project_dir: Path):
        _write_version_file(project_dir, name="project_name", current="1.0.0")
        result = runner.invoke(cli, ["set", "3.13-260819"], catch_exceptions=False)
        assert result.exit_code == 0
        data = _read_version_file(project_dir)
        assert _version_entry_composed(data["version"]["current"]) == "3.13-260819"

    def test_set_single_segment_still_rejected(self, runner: CliRunner, project_dir: Path):
        _write_version_file(project_dir, name="project_name", current="1.0.0")
        result = runner.invoke(cli, ["set", "3"], catch_exceptions=False)
        assert result.exit_code != 0
        assert "correct format" in result.output.lower()


class TestSvtProjectTwoSegment:
    """svt project reads two-segment versions correctly."""

    def test_project_version_two_segment(self, runner: CliRunner, project_dir: Path):
        _write_version_file(project_dir, name="project_name", current="3.13")
        result = runner.invoke(cli, ["project", "-v"], catch_exceptions=False)
        assert result.exit_code == 0
        assert result.output.strip() == "3.13"

    def test_project_version_two_segment_with_label(self, runner: CliRunner, project_dir: Path):
        _write_version_file(project_dir, name="project_name", current="3.13-260819")
        result = runner.invoke(cli, ["project", "-v"], catch_exceptions=False)
        assert result.exit_code == 0
        assert result.output.strip() == "3.13-260819"

    def test_project_docker_format_two_segment_with_label(self, runner: CliRunner, project_dir: Path):
        _write_version_file(project_dir, name="project_name", current="3.13-260819")
        result = runner.invoke(cli, ["project", "-d"], catch_exceptions=False)
        assert result.exit_code == 0
        assert result.output.strip() == "project_name/project_name:v3.13-260819"


class TestSvtBumpTwoSegment:
    """svt bump handles two-segment versions with correct error/success behavior."""

    def test_bump_minor_on_two_segment_produces_yymmdd_label(
        self, runner: CliRunner, project_dir: Path
    ):
        import re as _re
        _write_version_file(project_dir, name="project_name", current="3.13")
        result = runner.invoke(cli, ["bump", "--minor", "--skip-sync"], catch_exceptions=False)
        assert result.exit_code == 0
        data = _read_version_file(project_dir)
        new_ver = _version_entry_composed(data["version"]["current"])
        # Should be 3.14-YYMMDD
        assert _re.fullmatch(r"3\.14-[0-9]{6}", new_ver), f"Unexpected version: {new_ver}"

    def test_bump_minor_on_two_segment_with_explicit_label(
        self, runner: CliRunner, project_dir: Path
    ):
        _write_version_file(project_dir, name="project_name", current="3.13")
        result = runner.invoke(
            cli, ["bump", "--minor", "--label", "rc1", "--skip-sync"], catch_exceptions=False
        )
        assert result.exit_code == 0
        data = _read_version_file(project_dir)
        assert _version_entry_composed(data["version"]["current"]) == "3.14-rc1"

    def test_bump_minor_on_two_segment_with_short_label_flag(
        self, runner: CliRunner, project_dir: Path
    ):
        _write_version_file(project_dir, name="project_name", current="3.13")
        result = runner.invoke(
            cli, ["bump", "--minor", "-l", "rc1", "--skip-sync"], catch_exceptions=False
        )
        assert result.exit_code == 0
        data = _read_version_file(project_dir)
        assert _version_entry_composed(data["version"]["current"]) == "3.14-rc1"

    def test_bump_major_on_two_segment(self, runner: CliRunner, project_dir: Path):
        _write_version_file(project_dir, name="project_name", current="3.13")
        result = runner.invoke(
            cli, ["bump", "--major", "--label", "260819", "--skip-sync"], catch_exceptions=False
        )
        assert result.exit_code == 0
        data = _read_version_file(project_dir)
        assert _version_entry_composed(data["version"]["current"]) == "4.0-260819"

    def test_bump_major_on_two_segment_with_existing_label_uses_yymmdd(
        self, runner: CliRunner, project_dir: Path
    ):
        import re as _re
        _write_version_file(project_dir, name="project_name", current="3.13-old")
        result = runner.invoke(
            cli, ["bump", "--major", "--skip-sync"], catch_exceptions=False
        )
        assert result.exit_code == 0
        data = _read_version_file(project_dir)
        new_ver = _version_entry_composed(data["version"]["current"])
        # label is always today's YYMMDD when no --label given
        assert _re.fullmatch(r"4\.0-[0-9]{6}", new_ver), f"Unexpected version: {new_ver}"

    def test_bump_major_with_explicit_label_overrides_existing_label(
        self, runner: CliRunner, project_dir: Path
    ):
        _write_version_file(project_dir, name="project_name", current="3.13-old")
        result = runner.invoke(
            cli, ["bump", "--major", "--label", "260819", "--skip-sync"], catch_exceptions=False
        )
        assert result.exit_code == 0
        data = _read_version_file(project_dir)
        assert _version_entry_composed(data["version"]["current"]) == "4.0-260819"

    def test_bump_patch_on_two_segment_exits_nonzero(self, runner: CliRunner, project_dir: Path):
        _write_version_file(project_dir, name="project_name", current="3.13")
        result = runner.invoke(cli, ["bump", "--patch", "--skip-sync"], catch_exceptions=False)
        assert result.exit_code != 0
        assert "patch" in result.output.lower()
        assert "two-segment" in result.output.lower()

    def test_bump_default_on_two_segment_bumps_minor(self, runner: CliRunner, project_dir: Path):
        _write_version_file(project_dir, name="project_name", current="3.13")
        result = runner.invoke(cli, ["bump", "--skip-sync"], catch_exceptions=False)
        assert result.exit_code == 0
        data = _read_version_file(project_dir)
        bumped = _version_entry_composed(data["version"]["current"])
        assert bumped.startswith("3.14-")

    def test_bump_build_on_two_segment_exits_nonzero(self, runner: CliRunner, project_dir: Path):
        _write_version_file(project_dir, name="project_name", current="3.13")
        result = runner.invoke(cli, ["bump", "--build", "--skip-sync"], catch_exceptions=False)
        assert result.exit_code != 0

    def test_bump_label_on_three_segment_appends_label(self, runner: CliRunner, project_dir: Path):
        _write_version_file(project_dir, name="project_name", current="1.2.3")
        result = runner.invoke(
            cli, ["bump", "--label", "foo", "--skip-sync"], catch_exceptions=False
        )
        assert result.exit_code == 0
        data = _read_version_file(project_dir)
        assert _version_entry_composed(data["version"]["current"]) == "1.2.4-foo"

    def test_bump_invalid_label_exits_nonzero(self, runner: CliRunner, project_dir: Path):
        _write_version_file(project_dir, name="project_name", current="1.2.3")
        result = runner.invoke(
            cli, ["bump", "--label", "bad-label", "--skip-sync"], catch_exceptions=False
        )
        assert result.exit_code != 0
        assert "alphanumeric" in result.output.lower()

    def test_bump_previous_version_stored_correctly(self, runner: CliRunner, project_dir: Path):
        _write_version_file(project_dir, name="project_name", current="3.13")
        runner.invoke(
            cli, ["bump", "--minor", "--label", "snap", "--skip-sync"], catch_exceptions=False
        )
        data = _read_version_file(project_dir)
        assert _version_entry_composed(data["version"]["previous"]) == "3.13"
        assert _version_entry_composed(data["version"]["current"]) == "3.14-snap"


class TestSvtLoadProjectErrorMessage:
    """_load_project() error message mentions new formats."""

    def test_invalid_schema_error_mentions_new_formats(
        self, runner: CliRunner, project_dir: Path
    ):
        (project_dir / "version.yml").write_text(
            yaml.safe_dump({"name": "x", "version": {"current": "not-a-version"}})
        )
        result = runner.invoke(cli, ["project", "-v"], catch_exceptions=False)
        assert result.exit_code == 1
        assert "x.y" in result.output.lower() or "x.y" in result.output
        assert "invalid or incomplete" in result.output.lower()


class TestSvtProject:
    """Tests for `svt project` — read-only version.yml inspector."""

    def test_no_flags_prints_raw_file_contents(
        self, runner: CliRunner, project_dir: Path
    ):
        _write_version_file(
            project_dir, name="myapp", current="1.2.3", previous="1.2.2"
        )
        raw = (project_dir / "version.yml").read_text()
        result = runner.invoke(cli, ["project"], catch_exceptions=False)
        assert result.exit_code == 0
        assert result.output == raw

    def test_quiet_prints_name_then_version(
        self, runner: CliRunner, project_dir: Path
    ):
        _write_version_file(project_dir, name="myapp", current="1.2.3")
        result = runner.invoke(cli, ["project", "-q"], catch_exceptions=False)
        assert result.exit_code == 0
        lines = result.output.splitlines()
        assert lines[0] == "myapp"
        assert lines[1] == "1.2.3"

    def test_name_flag_prints_name(self, runner: CliRunner, project_dir: Path):
        _write_version_file(project_dir, name="myapp", current="1.2.3")
        result = runner.invoke(cli, ["project", "-n"], catch_exceptions=False)
        assert result.exit_code == 0
        assert result.output.strip() == "myapp"

    def test_version_flag_prints_current(
        self, runner: CliRunner, project_dir: Path
    ):
        _write_version_file(project_dir, name="myapp", current="1.2.3")
        result = runner.invoke(cli, ["project", "-v"], catch_exceptions=False)
        assert result.exit_code == 0
        assert result.output.strip() == "1.2.3"

    def test_previous_flag_prints_previous(
        self, runner: CliRunner, project_dir: Path
    ):
        _write_version_file(
            project_dir, name="myapp", current="1.2.3", previous="1.2.2"
        )
        result = runner.invoke(cli, ["project", "-p"], catch_exceptions=False)
        assert result.exit_code == 0
        assert result.output.strip() == "1.2.2"

    def test_previous_flag_when_none_outputs_empty(
        self, runner: CliRunner, project_dir: Path
    ):
        _write_version_file(project_dir, name="myapp", current="1.2.3")
        result = runner.invoke(cli, ["project", "-p"], catch_exceptions=False)
        assert result.exit_code == 0
        assert result.output.strip() == ""

    def test_manifest_flag_prints_manifest(
        self, runner: CliRunner, project_dir: Path
    ):
        (project_dir / "pyproject.toml").write_text(
            "[project]\nname = \"myapp\"\nversion = \"1.2.3\"\n"
        )
        _write_version_file(
            project_dir,
            name="myapp",
            current="1.2.3",
            manifest="pyproject.toml",
        )
        result = runner.invoke(cli, ["project", "-m"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "pyproject.toml" in result.output.strip()

    def test_manifest_flag_when_none_outputs_empty(
        self, runner: CliRunner, project_dir: Path
    ):
        _write_version_file(project_dir, name="myapp", current="1.2.3")
        result = runner.invoke(cli, ["project", "-m"], catch_exceptions=False)
        assert result.exit_code == 0
        assert result.output.strip() == ""

    def test_name_and_version_flags_two_lines_in_order(
        self, runner: CliRunner, project_dir: Path
    ):
        _write_version_file(project_dir, name="myapp", current="1.2.3")
        result = runner.invoke(
            cli, ["project", "-n", "-v"], catch_exceptions=False
        )
        assert result.exit_code == 0
        lines = result.output.splitlines()
        assert lines[0] == "myapp"
        assert lines[1] == "1.2.3"

    def test_all_field_flags_fixed_order_skips_none(
        self, runner: CliRunner, project_dir: Path
    ):
        (project_dir / "pyproject.toml").write_text(
            "[project]\nname = \"myapp\"\nversion = \"1.2.3\"\n"
        )
        _write_version_file(
            project_dir,
            name="myapp",
            current="1.2.3",
            previous="1.2.2",
            manifest="pyproject.toml",
        )
        result = runner.invoke(
            cli, ["project", "-n", "-v", "-p", "-m"], catch_exceptions=False
        )
        assert result.exit_code == 0
        lines = result.output.splitlines()
        assert lines[0] == "myapp"
        assert lines[1] == "1.2.3"
        assert lines[2] == "1.2.2"
        assert "pyproject.toml" in lines[3]

    def test_all_field_flags_none_values_skipped(
        self, runner: CliRunner, project_dir: Path
    ):
        _write_version_file(
            project_dir, name="myapp", current="1.2.3"
        )
        result = runner.invoke(
            cli, ["project", "-n", "-v", "-p", "-m"], catch_exceptions=False
        )
        assert result.exit_code == 0
        lines = result.output.splitlines()
        assert lines[0] == "myapp"
        assert lines[1] == "1.2.3"
        assert len(lines) == 2

    def test_quiet_and_name_flag_together_exits_nonzero(
        self, runner: CliRunner, project_dir: Path
    ):
        _write_version_file(project_dir, name="myapp", current="1.2.3")
        result = runner.invoke(
            cli, ["project", "-q", "-n"], catch_exceptions=False
        )
        assert result.exit_code != 0
        combined = (result.output or "") + (result.stderr or "")
        assert "mutually exclusive" in combined.lower()

    def test_missing_version_file_exits_nonzero(
        self, runner: CliRunner, project_dir: Path
    ):
        result = runner.invoke(cli, ["project"], catch_exceptions=False)
        assert result.exit_code != 0
        assert "svt init" in result.output

    def test_invalid_version_file_exits_nonzero(
        self, runner: CliRunner, project_dir: Path
    ):
        (project_dir / "version.yml").write_text(
            yaml.safe_dump({"name": "x", "version": {"current": "not-a-version"}})
        )
        result = runner.invoke(cli, ["project", "-n"], catch_exceptions=False)
        assert result.exit_code != 0


# ─── Migration shim: flat-string → VersionEntry ───────────────────────────────


class TestVersionMigrationShim:
    """Version model transparently migrates legacy flat-string on-disk format."""

    def test_flat_string_current_migrates(self):
        v = Version.model_validate({"current": "1.2.3"})
        assert v.current.composed() == "1.2.3"

    def test_flat_string_with_label_migrates(self):
        v = Version.model_validate({"current": "3.13-alpine", "previous": "3.12"})
        assert v.current.composed() == "3.13-alpine"
        assert v.previous is not None
        assert v.previous.composed() == "3.12"

    def test_yaml_float_previous_migrates(self):
        # YAML parses unquoted 3.12 as a float; shim must handle it
        raw = {"current": "3.13", "previous": 3.12}
        v = Version.model_validate(raw)
        assert v.previous is not None
        assert v.previous.composed() == "3.12"

    def test_structured_format_passes_through_unchanged(self):
        raw = {
            "current": {"semver": "1.2.3", "build": None, "tag_suffix": "rc1"},
            "previous": None,
        }
        v = Version.model_validate(raw)
        assert v.current.composed() == "1.2.3-rc1"
        assert v.previous is None

    def test_flat_to_structured_round_trip_via_svt(
        self, runner: CliRunner, project_dir: Path
    ):
        # Write a legacy flat-format file
        (project_dir / "version.yml").write_text(
            "name: myapp\nversion:\n  current: 2.5\n  previous: 2.4\nmanifest: null\n"
        )
        # Reading it should work transparently
        result = runner.invoke(cli, ["project", "-v"], catch_exceptions=False)
        assert result.exit_code == 0
        assert result.output.strip() == "2.5"
        # After a bump the file should use the new structured format
        result = runner.invoke(cli, ["bump", "--skip-sync"], catch_exceptions=False)
        assert result.exit_code == 0
        data = _read_version_file(project_dir)
        assert isinstance(data["version"]["current"], dict)
        composed = _version_entry_composed(data["version"]["current"])
        assert composed is not None and composed.startswith("2.6-")

