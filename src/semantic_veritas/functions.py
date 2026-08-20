# File: src/semantic_veritas/functions.py
# Author: Jonathan Belden
# Description: Core helpers for the semantic-veritas-tool.

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
import tomllib
from typing import Literal

from git import GitCommandError, PushInfo, Repo
import yaml

from semantic_veritas.data_models import Project, VersionEntry, SEMVER_PATTERN, SEMVER_TAG_PATTERN


DEFAULT_VERSION = "0.1.0"
VERSION_FILE_NAME = "version.yml"
PREVIOUS_VERSION_LABEL = " (previous version)"

_AMBIGUOUS_LOCK_MSG = (
    "Both poetry.lock and uv.lock are present; remove one lock file or use --skip-sync."
)
_NO_LOCK_MSG = (
    "No poetry.lock or uv.lock found; add one or use --skip-sync to skip package-manager alignment."
)
_POLYGLOT_NO_LOCK_MSG = (
    "Multiple manifests (pyproject.toml, package.json, Cargo.toml, or go.mod) were found with no "
    "lockfile and no manifest key in version.yml. Set manifest in version.yml to the authoritative "
    "file, or add poetry.lock or uv.lock for Python."
)
_PYPROJECT_NO_LOCK_MSG = (
    "pyproject.toml is authoritative for this bump but neither poetry.lock nor uv.lock was found. "
    "Add a lockfile or use --skip-sync to skip package-manager alignment."
)
_LOCK_WITHOUT_PYPROJECT_MSG = (
    "A poetry.lock or uv.lock file is present but pyproject.toml was not found; fix the project "
    "layout or use --skip-sync."
)


def version_file_path(base_dir: Path | None = None) -> Path:
    effective_dir = base_dir or Path.cwd()
    result = effective_dir / VERSION_FILE_NAME
    return result


def normalize_previous_version(value: str) -> str:
    result = value.strip().replace(PREVIOUS_VERSION_LABEL, "")
    return result


def format_previous_line(version: str) -> str:
    result = f"{version}{PREVIOUS_VERSION_LABEL}"
    return result


def validate_version(value: str) -> bool:
    result = bool(SEMVER_PATTERN.fullmatch(value.strip()))
    return result


def parse_version_tokens(value: str) -> dict[str, int | str | None]:
    cleaned_value = normalize_previous_version(value)
    # Try 3-segment first: X.Y.Z[.b][-label]
    three_seg_match = re.match(
        r"^([0-9]+)\.([0-9]+)\.([0-9]+)(?:\.([0-9]+))?(?:-([a-zA-Z0-9]+))?$",
        cleaned_value,
    )
    # Try 2-segment: X.Y[-label]
    two_seg_match = re.match(
        r"^([0-9]+)\.([0-9]+)(?:-([a-zA-Z0-9]+))?$",
        cleaned_value,
    )
    if three_seg_match:
        tokens: dict[str, int | str | None] = {
            "major": int(three_seg_match.group(1)),
            "minor": int(three_seg_match.group(2)),
            "patch": int(three_seg_match.group(3)),
            "build": int(three_seg_match.group(4)) if three_seg_match.group(4) is not None else None,
            "label": three_seg_match.group(5),  # may be None
        }
    elif two_seg_match:
        tokens = {
            "major": int(two_seg_match.group(1)),
            "minor": int(two_seg_match.group(2)),
            "patch": None,
            "build": None,
            "label": two_seg_match.group(3),  # may be None
        }
    else:
        raise ValueError(f"Cannot parse version tokens from: {value!r}")
    return tokens


def format_version_tokens(tokens: dict[str, int | str | None]) -> str:
    patch = tokens.get("patch")
    label = tokens.get("label")
    if patch is None:
        # Two-segment format: X.Y or X.Y-label
        base = f"{tokens['major']}.{tokens['minor']}"
    else:
        base = f"{tokens['major']}.{tokens['minor']}.{patch}"
        build = tokens.get("build")
        if build is not None:
            base = f"{base}.{build}"
    result = f"{base}-{label}" if label is not None else base
    return result


def read_project_version(base_dir: Path | None = None) -> Project:
    raw_value = yaml.safe_load(version_file_path(base_dir).read_text())
    if raw_value is None:
        raw_value = {}
    result = Project.model_validate(raw_value)
    return result


def detect_python_package_manager(base_dir: Path | None = None) -> str:
    cwd = base_dir or Path.cwd()
    has_poetry = (cwd / "poetry.lock").is_file()
    has_uv = (cwd / "uv.lock").is_file()
    if has_poetry and has_uv:
        raise ValueError(_AMBIGUOUS_LOCK_MSG)
    if has_poetry:
        result = "poetry"
    elif has_uv:
        result = "uv"
    else:
        raise ValueError(_NO_LOCK_MSG)
    return result


def run_python_package_manager_version_set(
    tool: str,
    version: str,
    base_dir: Path | None = None,
) -> None:
    cwd = base_dir or Path.cwd()
    if tool == "poetry":
        argv = ["poetry", "version", version]
    elif tool == "uv":
        argv = ["uv", "version", version]
    else:
        raise ValueError(f"unknown package manager: {tool!r}")
    completed = subprocess.run(
        argv,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        detail = stderr or stdout or f"exit {completed.returncode}"
        raise RuntimeError(f"{' '.join(argv)} failed: {detail}")


def sync_python_package_version(version: str, base_dir: Path | None = None) -> None:
    tool = detect_python_package_manager(base_dir)
    run_python_package_manager_version_set(tool, version, base_dir)


def _resolve_authoritative_manifest_path_for_bump(project: Project, cwd: Path) -> Path | None:
    manifests = discover_known_manifests(cwd)
    has_py = (cwd / "pyproject.toml").is_file()
    has_poetry = (cwd / "poetry.lock").is_file()
    has_uv = (cwd / "uv.lock").is_file()
    has_lock = has_poetry or has_uv

    resolved: Path | None = None

    if project.manifest is not None:
        stored = project.manifest
        candidate = stored if stored.is_absolute() else cwd / stored
        if not candidate.exists():
            raise ValueError(
                f"Stored manifest in version.yml does not exist: {candidate}. "
                "Restore the file, update the manifest key in version.yml, or use --skip-sync."
            )
        resolved = candidate.resolve()
    elif len(manifests) == 0:
        resolved = None
    elif len(manifests) == 1:
        resolved = manifests[0].resolve()
    elif has_lock and has_py:
        resolved = (cwd / "pyproject.toml").resolve()
    elif has_lock and not has_py:
        raise ValueError(_LOCK_WITHOUT_PYPROJECT_MSG)
    else:
        raise ValueError(_POLYGLOT_NO_LOCK_MSG)

    return resolved


def python_sync_action_for_bump(
    project: Project,
    base_dir: Path | None = None,
) -> Literal["skip", "run"]:
    cwd = (base_dir or Path.cwd()).resolve()
    has_poetry = (cwd / "poetry.lock").is_file()
    has_uv = (cwd / "uv.lock").is_file()

    authoritative = _resolve_authoritative_manifest_path_for_bump(project, cwd)
    action: Literal["skip", "run"] = "skip"

    if authoritative is None:
        action = "skip"
    elif authoritative.name != "pyproject.toml":
        action = "skip"
    elif has_poetry and has_uv:
        raise ValueError(_AMBIGUOUS_LOCK_MSG)
    elif has_poetry or has_uv:
        action = "run"
    else:
        raise ValueError(_PYPROJECT_NO_LOCK_MSG)

    return action


def _serialize_version_entry(entry: VersionEntry) -> dict:
    """Convert a VersionEntry to the structured mapping written to version.yml."""
    result = {
        "semver": entry.semver,
        "build": entry.build,
        "tag_suffix": entry.tag_suffix,
    }
    return result


def save_project_version(project: Project, base_dir: Path | None = None) -> None:
    root = (base_dir or Path.cwd()).resolve()
    serialized_manifest: str | None = None
    if project.manifest is not None:
        manifest_path = project.manifest
        if manifest_path.is_absolute():
            manifest_abs = manifest_path.resolve()
        else:
            manifest_abs = (root / manifest_path).resolve()
        try:
            serialized_manifest = manifest_abs.relative_to(root).as_posix()
        except ValueError:
            serialized_manifest = manifest_abs.as_posix()

    serialized_previous = (
        _serialize_version_entry(project.version.previous)
        if project.version.previous is not None
        else None
    )

    payload = {
        "name": project.name,
        "version": {
            "current": _serialize_version_entry(project.version.current),
            "previous": serialized_previous,
        },
        "manifest": serialized_manifest,
    }
    yaml_text = yaml.safe_dump(payload, sort_keys=False)
    version_file_path(base_dir).write_text(yaml_text)


def build_tag_message(project_name: str, version: str, note: str | None) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H:%M:%S")
    message = f"{project_name} v{version} -- {timestamp}"
    if note:
        message = f"{message} -- {note}"
    return message


def create_git_tag(version: str, message: str, repo_dir: Path | None = None) -> None:
    repo = Repo(repo_dir or Path.cwd(), search_parent_directories=True)
    existing = {tag.name for tag in repo.tags}
    if version in existing:
        raise ValueError("tag already exists")

    try:
        repo.create_tag(version, message=message)
    except GitCommandError as exc:
        raise RuntimeError("tag creation failed") from exc


def push_git_tag(version: str, repo_dir: Path | None = None) -> None:
    repo = Repo(repo_dir or Path.cwd(), search_parent_directories=True)
    if not repo.remotes:
        raise RuntimeError("no remote configured for tag push")

    push_infos = repo.remotes[0].push(version)
    failed = False
    for item in push_infos:
        if item.flags & (PushInfo.ERROR | PushInfo.REJECTED | PushInfo.REMOTE_REJECTED):
            failed = True
            break
    if failed:
        raise RuntimeError("tag push failed")


def delete_local_git_tag(version: str, repo_dir: Path | None = None) -> None:
    repo = Repo(repo_dir or Path.cwd(), search_parent_directories=True)
    try:
        repo.delete_tag(version)
    except GitCommandError:
        pass


def discover_known_manifests(base_dir: Path | None = None) -> list[Path]:
    cwd = base_dir or Path.cwd()
    candidates = [
        cwd / "pyproject.toml",
        cwd / "package.json",
        cwd / "Cargo.toml",
        cwd / "go.mod",
    ]
    existing = [candidate for candidate in candidates if candidate.exists()]
    result = existing
    return result


def is_supported_manifest(path: Path) -> bool:
    result = path.name in {"pyproject.toml", "package.json", "Cargo.toml", "go.mod"}
    return result


def parse_manifest(path: Path, base_dir: Path | None = None) -> tuple[str, str | None]:
    manifest_name = path.name
    project_name = path.parent.name
    detected_version: str | None = None

    if manifest_name == "pyproject.toml":
        data = tomllib.loads(path.read_text())
        project_block = data.get("project", {})
        project_name = project_block.get("name", project_name)
        detected_version = project_block.get("version")

    elif manifest_name == "Cargo.toml":
        data = tomllib.loads(path.read_text())
        package_block = data.get("package", {})
        project_name = package_block.get("name", project_name)
        detected_version = package_block.get("version")

    elif manifest_name == "package.json":
        data = json.loads(path.read_text())
        project_name = data.get("name", project_name)
        detected_version = data.get("version")

    elif manifest_name == "go.mod":
        module_line = ""
        for line in path.read_text().splitlines():
            if line.startswith("module "):
                module_line = line.strip()
                break
        module_value = module_line.removeprefix("module ").strip() or project_name
        project_name = module_value.split("/")[-1]
        detected_version = latest_semver_from_git(base_dir=base_dir)

    return project_name, detected_version


def latest_semver_from_git(base_dir: Path | None = None) -> str | None:
    version: str | None = None
    try:
        repo = Repo(base_dir or Path.cwd(), search_parent_directories=True)
        # Collect (major, minor, patch, build) tuples — only from 3-segment tags for sorting
        matched_versions: list[tuple[int, int, int, int]] = []
        for tag in repo.tags:
            matched = SEMVER_TAG_PATTERN.fullmatch(tag.name)
            if matched:
                normalized = matched.group(1)
                tokens = parse_version_tokens(normalized)
                if tokens["patch"] is not None:
                    matched_versions.append(
                        (
                            int(tokens["major"]),
                            int(tokens["minor"]),
                            int(tokens["patch"]),
                            int(tokens["build"] or 0),
                        )
                    )

        if matched_versions:
            latest = sorted(matched_versions)[-1]
            if latest[3] == 0:
                version = f"{latest[0]}.{latest[1]}.{latest[2]}"
            else:
                version = f"{latest[0]}.{latest[1]}.{latest[2]}.{latest[3]}"
    except Exception:
        version = None

    return version


def bump_version(
    current: str,
    bump_major: bool,
    bump_minor: bool,
    bump_patch: bool,
    bump_build: bool,
    label: str | None = None,
) -> str:
    token_count = sum([bump_major, bump_minor, bump_patch])
    if token_count > 1:
        raise ValueError("Choose only one of --major, --minor, or --patch")

    tokens = parse_version_tokens(current)
    is_two_segment = tokens["patch"] is None

    if is_two_segment:
        if bump_patch:
            raise ValueError("Cannot bump --patch on a two-segment version (X.Y); use --major or --minor")
        if bump_build:
            raise ValueError("Cannot bump --build on a two-segment version (X.Y); use --major or --minor")
        if bump_major:
            tokens["major"] = int(tokens["major"]) + 1  # type: ignore[arg-type]
            tokens["minor"] = 0
        else:
            tokens["minor"] = int(tokens["minor"]) + 1  # type: ignore[arg-type]
        tokens["patch"] = None
        tokens["build"] = None
        tokens["label"] = label
    else:
        if bump_major:
            tokens["major"] = int(tokens["major"]) + 1  # type: ignore[arg-type]
            tokens["minor"] = 0
            tokens["patch"] = 0
            tokens["build"] = 0 if bump_build else None
        elif bump_minor:
            tokens["minor"] = int(tokens["minor"]) + 1  # type: ignore[arg-type]
            tokens["patch"] = 0
            tokens["build"] = 0 if bump_build else None
        elif bump_patch:
            tokens["patch"] = int(tokens["patch"]) + 1  # type: ignore[arg-type]
            tokens["build"] = 0 if bump_build else None
        elif bump_build:
            base_build = int(tokens["build"] or 0)
            tokens["build"] = base_build + 1
        else:
            tokens["patch"] = int(tokens["patch"]) + 1  # type: ignore[arg-type]
        tokens["label"] = label

    result = format_version_tokens(tokens)
    return result
