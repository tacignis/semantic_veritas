# File: tests/test_semantic_veritas.py
# Author: Jonathan Belden
# Description: Tests for the semantic-veritas-tool.


from typer.testing import CliRunner
from pathlib import Path
from semantic_veritas_tool.semantic_veritas import cli


runner = CliRunner()


def test_svt_init():
    """
    Verifies that `svt init` does the following:
        - looks for common versioning files for common programming languages (python, javascript, rust, go, etc.)
        - sets the `project_name` variable to the name of the project if it exists, else sets it to the name of the project root directory
        - sets the `project_version` variable to the version if it exists, else sets it to 0.1.0
        - creates a version.txt file with the project name and version on two lines
            - format: "project_name\nX.Y.Z"
            - where X.Y.Z is the semantic version
        - prints a message indicating the version was saved to the version.txt file
    """
    result = runner.invoke(cli, ["init"])
    assert result.exit_code == 0
    assert "version.txt created" in result.output
    assert Path("version.txt").exists()
    assert Path("version.txt").read_text() == "project_name\n0.1.0"


def test_svt_version():
    """
    Verifies that `svt version` does the following:
        - looks for the version.txt file
        - if `version.txt` is not found, prints a message indicating the file was not found, suggest the user to run `svt init` and exits with a non-zero exit code
        - if found, prints the version
            - format: "project_name vX.Y.Z" --or-- "project_name vX.Y.Z.N" where N is the optional build number
        - if `-q|--quiet` is passed, prints only the version and exits with a zero exit code
            - format: "X.Y.Z" --or-- "X.Y.Z.N" where N is the optional build number
        - if `-n|--name-only` is passed, prints only the project name and exits with a zero exit code
            - format: "project_name"
        - if `-d|--docker-format` is passed, prints the version in Docker format
            - format: "project_name/project_name:vX.Y.Z" --or-- "project_name/project_name:vX.Y.Z.N" where N is the optional build number
        - if `-p|--previous` is passed:
            - prints the previous version if it exists on the 3rd line of the `version.txt` file, else prints a message indicating the previous version was not found
            - format: "X.Y.Z (previous version)" --or-- "X.Y.Z.N (previous version)" where N is the optional build number
            - follows the same rules as other flags for formatting the version
        - if `-t|--tag <optional message>` is passed, creates and pushes a git tag with the current version
            - format: "X.Y.Z[.N]" where N is the optional build number
            - specifies the tag message: "project_name vX.Y.Z[.N] -- YYYY-MM-DD_HH:MM:SS -- <optional message>"
            if tag already exists, prints a message indicating the tag already exists and exits with a non-zero exit code
            - if tag creation fails, prints a message indicating the tag creation failed and exits with a non-zero exit code, suggests the user investigate with git commands
            - if tag creation succeeds, prints a message indicating the tag was created and pushed
    """
    result = runner.invoke(cli, ["version"])
    assert result.exit_code == 0
    assert "project_name v0.1.0" in result.output

    result = runner.invoke(cli, ["version", "--quiet"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output

    result = runner.invoke(cli, ["version", "--project-name"])
    assert result.exit_code == 0
    assert "project_name" in result.output

    result = runner.invoke(cli, ["version", "--docker-format"])
    assert result.exit_code == 0
    assert "project_name/project_name:v0.1.0" in result.output


def test_svt_bump_default():
    """
    Verifies that `svt bump` does the following:
        - looks for the version.txt file
        - if not found, prints a message indicating the file was not found, suggest the user to run `svt init` and exits with a non-zero exit code
        - if found, increments the patch version by 1 (default action)
            - format: "X.Y.Z+1[.N]" where N is the optional build number
        - if `-b|--build` is passed, explicitly sets the build number to 0 (X.Y.Z+1.0)
        - saves the new version to the version.txt file (overwriting the previous version)
        - saves the old version to the 3rd line of the `version.txt` file
            - format: "project_name\nX.Y.Z[.b]\nX.Y.Z[.b] (previous version)"
        if `-t|--tag <optional message>` is passed, creates and pushes a git tag with the new version
            - format: "X.Y.Z[.b]" where b is the optional build number
            - specifies the tag message: "project_name vX.Y.Z[.b] -- YYYY-MM-DD_HH:MM:SS -- <optional message>"
            if tag already exists, revert all changes and exit with a non-zero exit code, print a message indicating the tag already exists
            - if tag creation fails, revert all changes and exit with a non-zero exit code, print a message indicating the tag creation failed, suggest the user investigate with git commands
            - if tag creation succeeds, prints a message indicating the tag was created and pushed
        - prints "project_name vX.Y.Z[.b] -> vX.Y.Z+1[.0]"
    """
    old_version = __tokenize_version(runner.invoke(cli, ["version", "--quiet"]))
    
    result = runner.invoke(cli, ["bump"])
    assert result.exit_code == 0
    new_default_version = __tokenize_version(runner.invoke(cli, ["version", "--quiet"]))
    assert new_default_version["major"] == old_version["major"]
    assert new_default_version["minor"] == old_version["minor"]
    assert new_default_version["patch"] == old_version["patch"] + 1
    assert new_default_version["build"] == old_version["build"]


def test_svt_bump_major():
    """
    Verifies that `svt bump [-x|--major]` does the following:
        - looks for the version.txt file
        - if not found, prints a message indicating the file was not found, suggest the user to run `svt init` and exits with a non-zero exit code
        - if found, increments the major version by 1 (X+1.0.0) and leaves build number off (implicit 0)
        - saves the new version to the version.txt file (overwriting the previous version)
        - saves the old version to the 3rd line of the `version.txt` file
            - format: "project_name\nX.Y.Z[.N]\nX.Y.Z[.N] (previous version)"
        if `-t|--tag <optional message>` is passed, creates and pushes a git tag with the new version
            - format: "X.Y.Z[.N]" where N is the optional build number
            - specifies the tag message: "project_name vX.Y.Z[.N] -- YYYY-MM-DD_HH:MM:SS -- <optional message>"
            if tag already exists, revert all changes and exit with a non-zero exit code, print a message indicating the tag already exists
            - if tag creation fails, revert all changes and exit with a non-zero exit code, print a message indicating the tag creation failed, suggest the user investigate with git commands
            - if tag creation succeeds, prints a message indicating the tag was created and pushed
        - prints "project_name vX.Y.Z[.N] -> vX+1.0.0[.N]"
    """
    old_version = __tokenize_version(runner.invoke(cli, ["version", "--quiet"]))

    result = runner.invoke(cli, ["bump", "--major"])
    assert result.exit_code == 0
    new_major_version = __tokenize_version(runner.invoke(cli, ["version", "--quiet"]))
    assert new_major_version["major"] == old_version["major"] + 1
    assert new_major_version["minor"] == 0
    assert new_major_version["patch"] == 0


def test_svt_bump_minor():
    """
    Verifies that `svt bump [-y|--minor]` does the following:
        - looks for the version.txt file
        - if not found, prints a message indicating the file was not found, suggest the user to run `svt init` and exits with a non-zero exit code
        - if found, increments the minor version by 1 (X.Y+1.0) and leaves build number off (implicit 0)
        - saves the new version to the version.txt file (overwriting the previous version)
        - saves the old version to the 3rd line of the `version.txt` file
            - format: "project_name\nX.Y.Z[.N]\nX.Y.Z[.N] (previous version)"
        if `-t|--tag <optional message>` is passed, creates and pushes a git tag with the new version
            - format: "X.Y.Z[.N]" where N is the optional build number
            - specifies the tag message: "project_name vX.Y.Z[.N] -- YYYY-MM-DD_HH:MM:SS -- <optional message>"
            if tag already exists, revert all changes and exit with a non-zero exit code, print a message indicating the tag already exists
            - if tag creation fails, revert all changes and exit with a non-zero exit code, print a message indicating the tag creation failed, suggest the user investigate with git commands
            - if tag creation succeeds, prints a message indicating the tag was created and pushed
        - prints a message indicating the version was bumped
    """
    old_version = __tokenize_version(runner.invoke(cli, ["version", "--quiet"]))

    result = runner.invoke(cli, ["bump", "--minor"])
    assert result.exit_code == 0
    new_minor_version = __tokenize_version(runner.invoke(cli, ["version", "--quiet"]))
    assert new_minor_version["major"] == old_version["major"]
    assert new_minor_version["minor"] == old_version["minor"] + 1
    assert new_minor_version["patch"] == 0


def test_svt_bump_patch():
    """
    Verifies that `svt bump [-z|--patch]` does the following:
        - looks for the version.txt file
        - if not found, prints a message indicating the file was not found, suggest the user to run `svt init` and exits with a non-zero exit code
        - if found, increments the patch version by 1 (X.Y.Z+1) and leaves build number off (implicit 0)
        - saves the new version to the version.txt file (overwriting the previous version)
        - saves the old version to the 3rd line of the `version.txt` file
            - format: "project_name\nX.Y.Z[.N]\nX.Y.Z[.N] (previous version)"
        if `-t|--tag <optional message>` is passed, creates and pushes a git tag with the new version
            - format: "X.Y.Z[.N]" where N is the optional build number
            - specifies the tag message: "project_name vX.Y.Z[.N] -- YYYY-MM-DD_HH:MM:SS -- <optional message>"
            if tag already exists, revert all changes and exit with a non-zero exit code, print a message indicating the tag already exists
            - if tag creation fails, revert all changes and exit with a non-zero exit code, print a message indicating the tag creation failed, suggest the user investigate with git commands
            - if tag creation succeeds, prints a message indicating the tag was created and pushed
        - prints a message indicating the version was bumped
    """
    old_version = __tokenize_version(runner.invoke(cli, ["version", "--quiet"]))

    result = runner.invoke(cli, ["bump", "--patch"])
    assert result.exit_code == 0
    new_patch_version = __tokenize_version(runner.invoke(cli, ["version", "--quiet"]))
    assert new_patch_version["major"] == old_version["major"]
    assert new_patch_version["minor"] == old_version["minor"]
    assert new_patch_version["patch"] == old_version["patch"] + 1


def test_svt_bump_build():
    """
    Verifies that `svt bump [-b|--build]` does the following:
        - looks for the version.txt file
        - if not found, prints a message indicating the file was not found, suggest the user to run `svt init` and exits with a non-zero exit code
        - if found, increments the build number by 1 (X.Y.Z.N+1) and leaves other versions unchanged
        - saves the new version to the version.txt file (overwriting the previous version)
        - saves the old version to the 3rd line of the `version.txt` file
            - format: "project_name\nX.Y.Z[.N]\nX.Y.Z[.N] (previous version)"
        if `-t|--tag <optional message>` is passed, creates and pushes a git tag with the new version
            - format: "X.Y.Z[.N]" where N is the optional build number
            - specifies the tag message: "project_name vX.Y.Z[.N] -- YYYY-MM-DD_HH:MM:SS -- <optional message>"
            if tag already exists, revert all changes and exit with a non-zero exit code, print a message indicating the tag already exists
            - if tag creation fails, revert all changes and exit with a non-zero exit code, print a message indicating the tag creation failed, suggest the user investigate with git commands
            - if tag creation succeeds, prints a message indicating the tag was created and pushed
        - prints a message indicating the version was bumped
    """
    old_version = __tokenize_version(runner.invoke(cli, ["version", "--quiet"]))

    result = runner.invoke(cli, ["bump", "--build"])
    assert result.exit_code == 0
    new_build_version = __tokenize_version(runner.invoke(cli, ["version", "--quiet"]))
    assert new_build_version["major"] == old_version["major"]
    assert new_build_version["minor"] == old_version["minor"]
    assert new_build_version["patch"] == old_version["patch"]
    assert new_build_version["build"] == old_version["build"] + 1


def test_svt_bump_build_major():
    """
    Verifies that `svt bump [-x|--major] [-b|--build]` does the following:
        - looks for the version.txt file
        - if not found, prints a message indicating the file was not found, suggest the user to run `svt init` and exits with a non-zero exit code
        - if found, increments the major version by 1 and explicitly sets the build number to 0 (X+1.0.0.0)
        - saves the new version to the version.txt file (overwriting the previous version)
        - saves the old version to the 3rd line of the `version.txt` file
            - format: "project_name\nX.Y.Z[.b]\nX.Y.Z[.b] (previous version)"
        if `-t|--tag <optional message>` is passed, creates and pushes a git tag with the new version
            - format: "X.Y.Z[.b]" where b is the optional build number
            - specifies the tag message: "project_name vX.Y.Z[.b] -- YYYY-MM-DD_HH:MM:SS -- <optional message>"
            if tag already exists, revert all changes and exit with a non-zero exit code, print a message indicating the tag already exists
            - if tag creation fails, revert all changes and exit with a non-zero exit code, print a message indicating the tag creation failed, suggest the user investigate with git commands
            - if tag creation succeeds, prints a message indicating the tag was created and pushed
        - prints a message indicating the version was bumped
    """
    old_version = __tokenize_version(runner.invoke(cli, ["version", "--quiet"]))

    result = runner.invoke(cli, ["bump", "--build", "--major"])
    assert result.exit_code == 0
    new_build_major_version = __tokenize_version(runner.invoke(cli, ["version", "--quiet"]))
    assert new_build_major_version["major"] == old_version["major"] + 1
    assert new_build_major_version["minor"] == 0
    assert new_build_major_version["patch"] == 0
    assert new_build_major_version["build"] == 0


def test_svt_bump_build_minor():
    """
    Verifies that `svt bump [-y|--minor] [-b|--build]` does the following:
        - looks for the version.txt file
        - if not found, prints a message indicating the file was not found, suggest the user to run `svt init` and exits with a non-zero exit code
        - if found, increments the minor version by 1 and explicitly sets the build number to 0 (X.Y+1.0.0)
        - saves the new version to the version.txt file (overwriting the previous version)
        - saves the old version to the 3rd line of the `version.txt` file
            - format: "project_name\nX.Y.Z[.b]\nX.Y.Z[.b] (previous version)"
        if `-t|--tag <optional message>` is passed, creates and pushes a git tag with the new version
            - format: "X.Y.Z[.b]" where b is the optional build number
            - specifies the tag message: "project_name vX.Y.Z[.b] -- YYYY-MM-DD_HH:MM:SS -- <optional message>"
            if tag already exists, revert all changes and exit with a non-zero exit code, print a message indicating the tag already exists
            - if tag creation fails, revert all changes and exit with a non-zero exit code, print a message indicating the tag creation failed, suggest the user investigate with git commands
            - if tag creation succeeds, prints a message indicating the tag was created and pushed
        - prints "project_name vX.Y.Z[.b] -> vX.Y+1.0[.0]"
    """
    old_version = __tokenize_version(runner.invoke(cli, ["version", "--quiet"]))

    result = runner.invoke(cli, ["bump", "--build", "--minor"])
    assert result.exit_code == 0
    new_build_minor_version = __tokenize_version(runner.invoke(cli, ["version", "--quiet"]))
    assert new_build_minor_version["major"] == old_version["major"]
    assert new_build_minor_version["minor"] == old_version["minor"] + 1
    assert new_build_minor_version["patch"] == 0
    assert new_build_minor_version["build"] == 0


def test_svt_bump_build_patch():
    """
    Verifies that `svt bump [-z|--patch] [-b|--build]` does the following:
        - looks for the version.txt file
        - if not found, prints a message indicating the file was not found, suggest the user to run `svt init` and exits with a non-zero exit code
        - if found, increments the patch version by 1 and explicitly sets the build number to 0 (X.Y.Z+1.0)
        - saves the new version to the version.txt file (overwriting the previous version)
        - saves the old version to the 3rd line of the `version.txt` file
            - format: "project_name\nX.Y.Z[.b]\nX.Y.Z[.b] (previous version)"
        if `-t|--tag <optional message>` is passed, creates and pushes a git tag with the new version
            - format: "X.Y.Z[.b]" where b is the optional build number
            - specifies the tag message: "project_name vX.Y.Z[.b] -- YYYY-MM-DD_HH:MM:SS -- <optional message>"
            if tag already exists, revert all changes and exit with a non-zero exit code, print a message indicating the tag already exists
            - if tag creation fails, revert all changes and exit with a non-zero exit code, print a message indicating the tag creation failed, suggest the user investigate with git commands
            - if tag creation succeeds, prints a message indicating the tag was created and pushed
        - prints "project_name vX.Y.Z[.b] -> vX.Y.Z+1[.0]"
    """
    old_version = __tokenize_version(runner.invoke(cli, ["version", "--quiet"]))

    result = runner.invoke(cli, ["bump", "--build", "--patch"])
    assert result.exit_code == 0
    new_build_patch_version = __tokenize_version(runner.invoke(cli, ["version", "--quiet"]))
    assert new_build_patch_version["major"] == old_version["major"]
    assert new_build_patch_version["minor"] == old_version["minor"]
    assert new_build_patch_version["patch"] == old_version["patch"] + 1
    assert new_build_patch_version["build"] == old_version["build"]


def test_svt_set_explicit_version():
    """
    Verifies that `svt set <version>` does the following:
        - looks for the version.txt file
        - if not found, prints a message indicating the file was not found, suggest the user to run `svt init` and exits with a non-zero exit code
        - if found, 
            - validates the specified version is in the correct format (X.Y.Z[.b])
                - regex: ^[0-9]+\.[0-9]+\.[0-9]+(\.[0-9]+)?$ where b is the optional build number
                - if not, prints a message indicating the version is not in the correct format and exits with a non-zero exit code
            - sets the version to the specified version
        - saves the new version to the version.txt file (overwriting the previous version)
        - saves the old version to the 3rd line of the `version.txt` file
            - format: "project_name\nX.Y.Z[.b]\nX.Y.Z[.b] (previous version)"
        if `-t|--tag <optional message>` is passed, creates and pushes a git tag with the new version
            - format: "X.Y.Z[.b]" where b is the optional build number
            - specifies the tag message: "project_name vX.Y.Z[.b] -- YYYY-MM-DD_HH:MM:SS -- <optional message>"
            if tag already exists, revert all changes and exit with a non-zero exit code, print a message indicating the tag already exists
            - if tag creation fails, revert all changes and exit with a non-zero exit code, print a message indicating the tag creation failed, suggest the user investigate with git commands
            - if tag creation succeeds, prints a message indicating the tag was created and pushed
        - prints "project_name vX.Y.Z[.b] -> vX.Y.Z[.b]"
    """
    old_version = __tokenize_version(runner.invoke(cli, ["version", "--quiet"]))

    previous_version = runner.invoke(cli, ["set", "1.2.3"])
    assert previous_version.exit_code == 0
    new_version = __tokenize_version(runner.invoke(cli, ["version", "--quiet"]))
    assert new_version["major"] == 1
    assert new_version["minor"] == 2
    assert new_version["patch"] == 3

    previous_version = __tokenize_version(runner.invoke(cli, ["version", "--previous"]))
    assert previous_version["major"] == old_version["major"]
    assert previous_version["minor"] == old_version["minor"]
    assert previous_version["patch"] == old_version["patch"]
    assert previous_version["build"] == old_version["build"]


def __tokenize_version(version: str) -> dict[str, int]:
    version = version.split(".").strip()
    return {
        "major": int(version[0]),
        "minor": int(version[1]),
        "patch": int(version[2]),
        "build": int(version[3]) if len(version) > 3 else None,
    }
