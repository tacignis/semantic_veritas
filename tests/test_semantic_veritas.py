# File: tests/test_semantic_veritas.py
# Author: Jonathan Belden
# Description: Tests for the semantic-veritas-tool.

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from typer.testing import CliRunner

from semantic_veritas import get_tool_version
from semantic_veritas.data_models import Project, SEMVER_PATTERN, Version
from semantic_veritas.functions import (
    detect_python_package_manager,
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
    result = runner.invoke(cli, ["version", "--quiet"], catch_exceptions=False)
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
    assert data["version"]["current"] == "1.0.1"


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
        "version": {"current": "0.1.0", "previous": None},
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
    assert data["version"]["current"] == "2.4.6"


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
    assert data["version"]["current"] == "9.9.9"


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
    assert data["version"]["current"] == "3.2.1"


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


def test_svt_version_missing_file_fails(runner: CliRunner, project_dir: Path):
    """
    Verifies that `svt version` exits non-zero when `version.yml` is missing.
    """
    result = runner.invoke(cli, ["version"], catch_exceptions=False)

    assert result.exit_code != 0
    assert "run `svt init`" in result.output.lower()


def test_validate_version_uses_shared_semver_rule():
    assert validate_version("1.2.3")
    assert validate_version("1.2.3.4")
    assert validate_version("  2.0.0.1  ")
    assert not validate_version("1.2")
    assert not validate_version("v1.2.3")
    assert SEMVER_PATTERN.fullmatch("1.2.3.4")


@pytest.mark.parametrize(
    "cli_args",
    [
        ["version"],
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
        ["version"],
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


def test_svt_version_formats(runner: CliRunner, project_dir: Path):
    _write_version_file(project_dir, name="project_name", current="0.1.0")

    result = runner.invoke(cli, ["version"], catch_exceptions=False)
    assert result.exit_code == 0
    assert result.output.strip() == "project_name v0.1.0"

    result = runner.invoke(cli, ["version", "--quiet"], catch_exceptions=False)
    assert result.exit_code == 0
    assert result.output.strip() == "0.1.0"

    result = runner.invoke(cli, ["version", "--name-only"], catch_exceptions=False)
    assert result.exit_code == 0
    assert result.output.strip() == "project_name"

    result = runner.invoke(cli, ["version", "--docker-format"], catch_exceptions=False)
    assert result.exit_code == 0
    assert result.output.strip() == "project_name/project_name:v0.1.0"


def test_svt_version_previous_missing_fails(runner: CliRunner, project_dir: Path):
    _write_version_file(project_dir, name="project_name", current="0.1.0")

    result = runner.invoke(cli, ["version", "--previous"], catch_exceptions=False)

    assert result.exit_code != 0
    assert "previous version was not found" in result.output.lower()


def test_svt_version_previous_formats(runner: CliRunner, project_dir: Path):
    _write_version_file(project_dir, name="project_name", current="1.4.2", previous="1.4.1")

    result = runner.invoke(cli, ["version", "--previous"], catch_exceptions=False)
    assert result.exit_code == 0
    assert result.output.strip() == "1.4.1 (previous version)"


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
    assert _read_version_file(project_dir)["version"]["current"] == "1.2.4"


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
    assert _read_version_file(project_dir)["version"]["current"] == "1.2.3"
    assert _read_version_file(project_dir)["version"]["previous"] is None
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
    assert _read_version_file(project_dir)["version"]["current"] == "1.2.4"


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
    assert _read_version_file(project_dir)["version"]["current"] == "1.2.4"


def test_svt_bump_stored_manifest_missing_fails_with_guidance_and_reverts(
    runner: CliRunner,
    project_dir: Path,
):
    _write_version_file(project_dir, name="pkg", current="1.2.3", manifest="Cargo.toml")

    result = runner.invoke(cli, ["bump"], catch_exceptions=False)

    assert result.exit_code == 1
    assert _read_version_file(project_dir)["version"]["current"] == "1.2.3"
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
    assert _read_version_file(project_dir)["version"]["current"] == "1.2.3"
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
    assert _read_version_file(project_dir)["version"]["current"] == "1.2.3"
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
    assert _read_version_file(project_dir)["version"]["current"] == "1.2.4"


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
    assert _read_version_file(project_dir)["version"]["current"] == "1.2.4"


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
    assert _read_version_file(project_dir)["version"]["current"] == "1.2.3"
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
    assert _read_version_file(project_dir)["version"]["current"] == "1.2.3"
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
    assert _read_version_file(project_dir)["version"]["current"] == "1.2.3"
    assert _read_version_file(project_dir)["version"]["previous"] is None
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
def test_svt_version_with_tag_calls_create_and_push_helpers(
    mock_create: MagicMock,
    mock_push: MagicMock,
    runner: CliRunner,
    project_dir: Path,
):
    _write_version_file(project_dir, name="project_name", current="1.2.3")

    result = runner.invoke(
        cli,
        ["version", "--tag", "note"],
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
    assert _read_version_file(project_dir)["version"]["previous"] == "1.2.3"


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

    previous_result = runner.invoke(cli, ["version", "--previous"], catch_exceptions=False)
    previous_version = _tokenize_version(previous_result.output)
    assert previous_version == old_version


def test_svt_set_rejects_invalid_version_format(runner: CliRunner, project_dir: Path):
    _write_version_file(project_dir, name="project_name", current="0.1.0")

    result = runner.invoke(cli, ["set", "1.2"], catch_exceptions=False)

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
    assert data["version"]["current"] == "2.4.6"


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
    assert data["version"]["current"] == "1.2.3"
    assert data["version"]["previous"] == "0.9.0"


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
    assert data["version"]["current"] == "9.9.9"
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
    assert data["version"]["current"] == "2.4.6"
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
    assert data["version"]["current"] == "3.2.1"
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
    assert data["version"]["current"] == "3.0.0"
    assert data["version"]["previous"] is None
