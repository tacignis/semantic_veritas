# File: src/semantic_veritas/semantic_veritas.py
# Author: Jonathan Belden
# Description: A universal tool for setting and determining a project's semantic versioning.

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import typer
import yaml
from pydantic import ValidationError

from semantic_veritas import get_tool_version
from semantic_veritas.data_models import Project, Version
from semantic_veritas.functions import (
    DEFAULT_VERSION,
    PREVIOUS_VERSION_LABEL,
    build_tag_message,
    bump_version,
    create_git_tag,
    delete_local_git_tag,
    discover_known_manifests,
    is_supported_manifest,
    parse_manifest,
    push_git_tag,
    python_sync_action_for_bump,
    read_project_version,
    save_project_version,
    sync_python_package_version,
    validate_version,
    version_file_path,
)


def _version_option_callback(value: bool) -> None:
    if value:
        typer.echo(get_tool_version())
        raise typer.Exit(code=0)


def _cli_callback(
    ctx: typer.Context,
    _version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Print the semantic-veritas tool version and exit.",
        callback=_version_option_callback,
        is_eager=True,
    ),
) -> None:
    pass


cli = typer.Typer(
    name="svt",
    help=(
        "Semantic versioning helper for projects. "
        f"Tool package (semantic-veritas): {get_tool_version()}."
    ),
    callback=_cli_callback,
)


def _missing_version_file_message() -> str:
    message = "version.yml was not found. Please run `svt init`."
    return message


def _parse_manifest_or_exit(path: Path, base_dir: Path) -> tuple[str, str | None]:
    result: tuple[str, str | None]
    try:
        result = parse_manifest(path, base_dir=base_dir)
    except (json.JSONDecodeError, tomllib.TOMLDecodeError):
        typer.echo(
            f"Manifest could not be parsed: {path}. "
            "Fix the file syntax or pass a different --manifest path.",
            err=True,
        )
        raise typer.Exit(code=1)
    except (OSError, UnicodeDecodeError):
        typer.echo(
            f"Manifest could not be read: {path}. "
            "Check permissions, UTF-8 encoding, or pass --manifest.",
            err=True,
        )
        raise typer.Exit(code=1)
    return result


def _load_project() -> Project:
    project: Project
    try:
        project = read_project_version()
    except yaml.YAMLError:
        typer.echo(
            "version.yml could not be parsed as YAML. "
            "Fix the syntax or remove the file and run `svt init`."
        )
        raise typer.Exit(code=1)
    except ValidationError:
        typer.echo(
            "version.yml is invalid or incomplete. "
            "It must include name and version.current (semver X.Y.Z or X.Y.Z.b); "
            "optional keys: version.previous, manifest."
        )
        raise typer.Exit(code=1)
    return project


def _prompt_for_manifest(candidates: list[Path]) -> Path:
    typer.echo("Multiple version sources found; which one is authoritative?\n")
    for index, candidate in enumerate(candidates, start=1):
        typer.echo(f"{index}) {candidate.name}")

    selected_manifest: Path | None = None
    while selected_manifest is None:
        value = typer.prompt("\n> ")
        if not value.isdigit():
            typer.echo(f"Enter a number between 1 and {len(candidates)}")
            continue

        index = int(value)
        if index < 1 or index > len(candidates):
            typer.echo(f"Enter a number between 1 and {len(candidates)}")
            continue

        selected_manifest = candidates[index - 1]

    return selected_manifest


def _resolve_manifest(manifest: str | None) -> Path | None:
    selected_manifest: Path | None = None
    if manifest:
        candidate = Path(manifest)
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        if not candidate.exists():
            typer.echo(
                f"Manifest does not exist: {candidate}. "
                "Fix the path or pass a different --manifest value.",
                err=True,
            )
            raise typer.Exit(code=1)
        if not is_supported_manifest(candidate):
            typer.echo(
                f"Unsupported manifest type: {candidate.name}. "
                "Use pyproject.toml, package.json, Cargo.toml, or go.mod.",
                err=True,
            )
            raise typer.Exit(code=1)
        selected_manifest = candidate
    else:
        manifests = discover_known_manifests()
        if len(manifests) == 1:
            selected_manifest = manifests[0]
        elif len(manifests) > 1:
            selected_manifest = _prompt_for_manifest(manifests)

    return selected_manifest


def _normalize_manifest_path(path: Path | None, base_dir: Path) -> Path | None:
    normalized: Path | None = None
    if path is not None:
        candidate = path if path.is_absolute() else base_dir / path
        normalized = candidate.resolve()
    return normalized


def _manifest_paths_equal(
    left: Path | None,
    right: Path | None,
    base_dir: Path,
) -> bool:
    equal = False
    left_norm = _normalize_manifest_path(left, base_dir)
    right_norm = _normalize_manifest_path(right, base_dir)
    if left_norm is None and right_norm is None:
        equal = True
    elif left_norm is not None and right_norm is not None:
        equal = left_norm == right_norm
    return equal


def _resolve_authoritative_manifest(
    manifest_option: str | None,
    project: Project,
) -> Path:
    cwd = Path.cwd()
    resolved: Path | None = None
    if manifest_option:
        candidate = Path(manifest_option)
        if not candidate.is_absolute():
            candidate = cwd / candidate
        if not candidate.exists():
            typer.echo(
                f"Manifest does not exist: {candidate}. "
                "Fix the path or omit --manifest to use version.yml or discovery.",
                err=True,
            )
            raise typer.Exit(code=1)
        if not is_supported_manifest(candidate):
            typer.echo(
                f"Unsupported manifest type: {candidate.name}. "
                "Use pyproject.toml, package.json, Cargo.toml, or go.mod.",
                err=True,
            )
            raise typer.Exit(code=1)
        resolved = candidate.resolve()
    elif project.manifest is not None:
        stored = project.manifest
        candidate = stored if stored.is_absolute() else cwd / stored
        if not candidate.exists():
            typer.echo(
                f"Stored manifest in version.yml does not exist: {candidate}. "
                "Restore the file, update the manifest key in version.yml, or pass --manifest.",
                err=True,
            )
            raise typer.Exit(code=1)
        if not is_supported_manifest(candidate):
            typer.echo(
                f"Stored manifest in version.yml is not a supported type: {candidate.name}. "
                "Point manifest to pyproject.toml, package.json, Cargo.toml, or go.mod.",
                err=True,
            )
            raise typer.Exit(code=1)
        resolved = candidate.resolve()
    else:
        manifests = discover_known_manifests()
        if len(manifests) == 0:
            typer.echo(
                "No manifest could be resolved: version.yml has no manifest key and no "
                "pyproject.toml, package.json, Cargo.toml, or go.mod was found here. "
                "Add a supported manifest or run `svt init --manifest <path>`.",
                err=True,
            )
            raise typer.Exit(code=1)
        if len(manifests) == 1:
            resolved = manifests[0].resolve()
        else:
            resolved = _prompt_for_manifest(manifests).resolve()

    return resolved


def _get_requested_version(project: Project, previous: bool) -> str:
    version_value = project.version.current
    if previous:
        if project.version.previous is None:
            typer.echo("Previous version was not found.")
            raise typer.Exit(code=1)
        version_value = project.version.previous
    return version_value


@cli.command()
def init(
    manifest: str | None = typer.Option(
        None,
        "--manifest",
        help="Known manifest path: pyproject.toml, package.json, Cargo.toml, or go.mod",
    ),
):
    """
    Initialize the project with a version.yml file.
    """
    selected_manifest = _resolve_manifest(manifest)

    project_name = Path.cwd().name
    project_version = DEFAULT_VERSION

    if selected_manifest is not None:
        parsed_name, parsed_version = _parse_manifest_or_exit(
            selected_manifest,
            base_dir=Path.cwd(),
        )
        project_name = parsed_name
        if parsed_version and validate_version(parsed_version):
            project_version = parsed_version

    project = Project(
        name=project_name,
        version=Version(current=project_version),
        manifest=selected_manifest,
    )
    save_project_version(project)
    typer.echo("version.yml created")


@cli.command()
def about() -> None:
    """
    Print the semantic-veritas tool version (from package metadata).
    """
    typer.echo(get_tool_version())


@cli.command()
def reconcile(
    manifest: str | None = typer.Option(
        None,
        "--manifest",
        help="Known manifest path: pyproject.toml, package.json, Cargo.toml, or go.mod",
    ),
):
    """
    Refresh version.yml name and version from the authoritative manifest.
    """
    if not version_file_path().exists():
        typer.echo(_missing_version_file_message())
        raise typer.Exit(code=1)

    project = _load_project()
    base_dir = Path.cwd()
    authoritative = _resolve_authoritative_manifest(manifest, project)
    parsed_name, parsed_version = _parse_manifest_or_exit(authoritative, base_dir=base_dir)

    old_current = project.version.current
    new_current = old_current
    if parsed_version is not None and validate_version(parsed_version):
        new_current = parsed_version

    new_previous = project.version.previous
    if new_current != old_current:
        new_previous = None

    updated = Project(
        name=parsed_name,
        version=Version(current=new_current, previous=new_previous),
        manifest=authoritative,
    )

    unchanged = (
        project.name == updated.name
        and project.version.current == updated.version.current
        and project.version.previous == updated.version.previous
        and _manifest_paths_equal(project.manifest, updated.manifest, base_dir)
    )
    if not unchanged:
        save_project_version(updated)
        typer.echo("version.yml updated")


@cli.command()
def version(
    quiet: bool = typer.Option(False, "--quiet", "-q"),
    name_only: bool = typer.Option(False, "--name-only", "-n"),
    docker_format: bool = typer.Option(False, "--docker-format", "-d"),
    previous: bool = typer.Option(False, "--previous", "-p"),
    tag: str | None = typer.Option(None, "--tag", "-t"),
):
    """
    Print the project version from version.yml.

    This reads the managed project state, not the semantic-veritas tool package.
    For the tool itself, use ``svt --version`` (or ``-V``).
    """
    if not version_file_path().exists():
        typer.echo(_missing_version_file_message())
        raise typer.Exit(code=1)

    project = _load_project()
    requested_version = _get_requested_version(project, previous=previous)

    if tag is not None:
        tag_message = build_tag_message(project.name, requested_version, tag)
        try:
            create_git_tag(requested_version, tag_message)
        except ValueError:
            typer.echo("Tag already exists")
            raise typer.Exit(code=1)
        except RuntimeError:
            typer.echo("Tag creation failed. Please investigate with git commands.")
            raise typer.Exit(code=1)
        try:
            push_git_tag(requested_version)
        except RuntimeError:
            delete_local_git_tag(requested_version)
            typer.echo(
                "Tag was created locally but could not be pushed. "
                "The local tag was removed if present.",
                err=True,
            )
            raise typer.Exit(code=1)
        typer.echo("Tag created and pushed")

    output = f"{project.name} v{requested_version}"
    if quiet:
        output = requested_version
    elif name_only:
        output = project.name
    elif docker_format:
        output = f"{project.name}/{project.name}:v{requested_version}"

    if previous and not quiet and not name_only and not docker_format:
        output = f"{requested_version}{PREVIOUS_VERSION_LABEL}"

    typer.echo(output)


@cli.command()
def bump(
    major: bool = typer.Option(False, "--major", "-x"),
    minor: bool = typer.Option(False, "--minor", "-y"),
    patch: bool = typer.Option(False, "--patch", "-z"),
    build: bool = typer.Option(False, "--build", "-b"),
    tag: str | None = typer.Option(None, "--tag", "-t"),
    skip_sync: bool = typer.Option(
        False,
        "--skip-sync",
        help=(
            "Skip package-manager alignment for this bump "
            "(currently uv/poetry when applicable)."
        ),
    ),
):
    """
    Bump the version.
    """
    if not version_file_path().exists():
        typer.echo(_missing_version_file_message())
        raise typer.Exit(code=1)

    project = _load_project()
    old_version = project.version.current

    try:
        new_version = bump_version(
            current=old_version,
            bump_major=major,
            bump_minor=minor,
            bump_patch=patch,
            bump_build=build,
        )
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)

    updated_project = Project(
        name=project.name,
        version=Version(current=new_version, previous=old_version),
        manifest=project.manifest,
    )
    save_project_version(updated_project)

    if not skip_sync:
        try:
            sync_action = python_sync_action_for_bump(project)
        except ValueError as exc:
            save_project_version(project)
            typer.echo(
                f"Package manager configuration error ({exc}). "
                "version.yml was reverted. "
                "Use --skip-sync to skip package-manager alignment when appropriate.",
                err=True,
            )
            raise typer.Exit(code=1)
        if sync_action == "run":
            try:
                sync_python_package_version(new_version)
            except ValueError as exc:
                save_project_version(project)
                typer.echo(
                    f"Package manager configuration error ({exc}). "
                    "version.yml was reverted. "
                    "Use --skip-sync to skip package-manager alignment.",
                    err=True,
                )
                raise typer.Exit(code=1)
            except RuntimeError as exc:
                save_project_version(project)
                typer.echo(
                    f"Package manager alignment failed ({exc}). "
                    "version.yml was reverted. "
                    "Use --skip-sync to skip package-manager alignment.",
                    err=True,
                )
                raise typer.Exit(code=1)

    if tag is not None:
        tag_message = build_tag_message(project.name, new_version, tag)
        try:
            create_git_tag(new_version, tag_message)
        except ValueError:
            save_project_version(project)
            typer.echo("Tag already exists")
            raise typer.Exit(code=1)
        except RuntimeError:
            save_project_version(project)
            typer.echo("Tag creation failed. Please investigate with git commands.")
            raise typer.Exit(code=1)
        try:
            push_git_tag(new_version)
        except RuntimeError:
            save_project_version(project)
            delete_local_git_tag(new_version)
            typer.echo(
                "Tag push failed after creating the tag. "
                "version.yml was reverted and the local tag was removed if present.",
                err=True,
            )
            raise typer.Exit(code=1)
        typer.echo("Tag created and pushed")

    typer.echo(f"{project.name} v{old_version} -> v{new_version}")


@cli.command(name="set")
def set_version(
    new_version: str = typer.Argument(...),
    tag: str | None = typer.Option(None, "--tag", "-t"),
):
    """
    Set the version.
    """
    if not version_file_path().exists():
        typer.echo(_missing_version_file_message())
        raise typer.Exit(code=1)

    if not validate_version(new_version):
        typer.echo("Version is not in the correct format (X.Y.Z[.b]).")
        raise typer.Exit(code=1)

    project = _load_project()
    old_version = project.version.current

    updated_project = Project(
        name=project.name,
        version=Version(current=new_version, previous=old_version),
        manifest=project.manifest,
    )
    save_project_version(updated_project)

    if tag is not None:
        tag_message = build_tag_message(project.name, new_version, tag)
        try:
            create_git_tag(new_version, tag_message)
        except ValueError:
            save_project_version(project)
            typer.echo("Tag already exists")
            raise typer.Exit(code=1)
        except RuntimeError:
            save_project_version(project)
            typer.echo("Tag creation failed. Please investigate with git commands.")
            raise typer.Exit(code=1)
        try:
            push_git_tag(new_version)
        except RuntimeError:
            save_project_version(project)
            delete_local_git_tag(new_version)
            typer.echo(
                "Tag push failed after creating the tag. "
                "version.yml was reverted and the local tag was removed if present.",
                err=True,
            )
            raise typer.Exit(code=1)
        typer.echo("Tag created and pushed")

    typer.echo(f"{project.name} v{old_version} -> v{new_version}")
