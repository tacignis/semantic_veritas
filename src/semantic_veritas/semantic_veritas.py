# File: src/semantic_veritas_tool/semantic_veritas.py
# Author: Jonathan Belden
# Description: A universal tool for setting and determining a project's semantic versioning.

from __future__ import annotations

from pathlib import Path

import typer
import yaml
from pydantic import ValidationError

from semantic_veritas.data_models import Project, Version
from semantic_veritas.functions import (
    DEFAULT_VERSION,
    PREVIOUS_VERSION_LABEL,
    build_tag_message,
    bump_version,
    create_and_push_git_tag,
    discover_known_manifests,
    is_supported_manifest,
    parse_manifest,
    read_project_version,
    save_project_version,
    validate_version,
    version_file_path,
)


cli = typer.Typer()


def _missing_version_file_message() -> str:
    message = "version.yml was not found. Please run `svt init`."
    return message


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
            typer.echo("Manifest path does not exist.")
            raise typer.Exit(code=1)
        if not is_supported_manifest(candidate):
            typer.echo("The selected path is not a supported manifest type.")
            raise typer.Exit(code=1)
        selected_manifest = candidate
    else:
        manifests = discover_known_manifests()
        if len(manifests) == 1:
            selected_manifest = manifests[0]
        elif len(manifests) > 1:
            selected_manifest = _prompt_for_manifest(manifests)

    return selected_manifest


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
        parsed_name, parsed_version = parse_manifest(selected_manifest, base_dir=Path.cwd())
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
def version(
    quiet: bool = typer.Option(False, "--quiet", "-q"),
    name_only: bool = typer.Option(False, "--name-only", "-n"),
    docker_format: bool = typer.Option(False, "--docker-format", "-d"),
    previous: bool = typer.Option(False, "--previous", "-p"),
    tag: str | None = typer.Option(None, "--tag", "-t"),
):
    """
    Print the current version.
    """
    if not version_file_path().exists():
        typer.echo(_missing_version_file_message())
        raise typer.Exit(code=1)

    project = _load_project()
    requested_version = _get_requested_version(project, previous=previous)

    if tag is not None:
        tag_message = build_tag_message(project.name, requested_version, tag)
        try:
            create_and_push_git_tag(requested_version, tag_message)
            typer.echo("Tag created and pushed")
        except ValueError:
            typer.echo("Tag already exists")
            raise typer.Exit(code=1)
        except Exception:
            typer.echo("Tag creation failed. Please investigate with git commands.")
            raise typer.Exit(code=1)

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

    if tag is not None:
        tag_message = build_tag_message(project.name, new_version, tag)
        try:
            create_and_push_git_tag(new_version, tag_message)
            typer.echo("Tag created and pushed")
        except ValueError:
            save_project_version(project)
            typer.echo("Tag already exists")
            raise typer.Exit(code=1)
        except Exception:
            save_project_version(project)
            typer.echo("Tag creation failed. Please investigate with git commands.")
            raise typer.Exit(code=1)

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
            create_and_push_git_tag(new_version, tag_message)
            typer.echo("Tag created and pushed")
        except ValueError:
            save_project_version(project)
            typer.echo("Tag already exists")
            raise typer.Exit(code=1)
        except Exception:
            save_project_version(project)
            typer.echo("Tag creation failed. Please investigate with git commands.")
            raise typer.Exit(code=1)

    typer.echo(f"{project.name} v{old_version} -> v{new_version}")
