# File: tests/test_semantic_veritas.py
# Author: Jonathan Belden
# Description: Tests for the semantic-veritas-tool.

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from semantic_veritas_tool.data_models import SEMVER_PATTERN
from semantic_veritas_tool.functions import validate_version
from semantic_veritas_tool.semantic_veritas import cli


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


def test_svt_bump_default(runner: CliRunner, project_dir: Path):
    _write_version_file(project_dir, name="project_name", current="1.2.3")
    old_version = _tokenize_version(_quiet_version(runner, project_dir))

    result = runner.invoke(cli, ["bump"], catch_exceptions=False)

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

    result = runner.invoke(cli, ["bump", "--major"], catch_exceptions=False)

    assert result.exit_code == 0
    new_version = _tokenize_version(_quiet_version(runner, project_dir))
    assert new_version["major"] == old_version["major"] + 1
    assert new_version["minor"] == 0
    assert new_version["patch"] == 0
    assert new_version["build"] is None


def test_svt_bump_minor(runner: CliRunner, project_dir: Path):
    _write_version_file(project_dir, name="project_name", current="1.2.3")
    old_version = _tokenize_version(_quiet_version(runner, project_dir))

    result = runner.invoke(cli, ["bump", "--minor"], catch_exceptions=False)

    assert result.exit_code == 0
    new_version = _tokenize_version(_quiet_version(runner, project_dir))
    assert new_version["major"] == old_version["major"]
    assert new_version["minor"] == old_version["minor"] + 1
    assert new_version["patch"] == 0
    assert new_version["build"] is None


def test_svt_bump_patch(runner: CliRunner, project_dir: Path):
    _write_version_file(project_dir, name="project_name", current="1.2.3")
    old_version = _tokenize_version(_quiet_version(runner, project_dir))

    result = runner.invoke(cli, ["bump", "--patch"], catch_exceptions=False)

    assert result.exit_code == 0
    new_version = _tokenize_version(_quiet_version(runner, project_dir))
    assert new_version["major"] == old_version["major"]
    assert new_version["minor"] == old_version["minor"]
    assert new_version["patch"] == old_version["patch"] + 1
    assert new_version["build"] is None


def test_svt_bump_build_from_implicit_zero(runner: CliRunner, project_dir: Path):
    _write_version_file(project_dir, name="project_name", current="1.2.3")

    result = runner.invoke(cli, ["bump", "--build"], catch_exceptions=False)

    assert result.exit_code == 0
    new_version = _tokenize_version(_quiet_version(runner, project_dir))
    assert new_version == {"major": 1, "minor": 2, "patch": 3, "build": 1}


def test_svt_bump_build_major(runner: CliRunner, project_dir: Path):
    _write_version_file(project_dir, name="project_name", current="1.2.3.9")

    result = runner.invoke(cli, ["bump", "--build", "--major"], catch_exceptions=False)

    assert result.exit_code == 0
    new_version = _tokenize_version(_quiet_version(runner, project_dir))
    assert new_version == {"major": 2, "minor": 0, "patch": 0, "build": 0}


def test_svt_bump_build_minor(runner: CliRunner, project_dir: Path):
    _write_version_file(project_dir, name="project_name", current="1.2.3.9")

    result = runner.invoke(cli, ["bump", "--build", "--minor"], catch_exceptions=False)

    assert result.exit_code == 0
    new_version = _tokenize_version(_quiet_version(runner, project_dir))
    assert new_version == {"major": 1, "minor": 3, "patch": 0, "build": 0}


def test_svt_bump_build_patch(runner: CliRunner, project_dir: Path):
    _write_version_file(project_dir, name="project_name", current="1.2.3.9")

    result = runner.invoke(cli, ["bump", "--build", "--patch"], catch_exceptions=False)

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
