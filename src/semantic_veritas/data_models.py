# File: src/semantic_veritas/data_models.py
# Author: Jonathan Belden
# Description: Data models for the Semantic Veritas Tool


import re
from pathlib import Path

from pydantic import BaseModel, field_validator, model_validator

# Single source for version text. Accepted formats:
#   X.Y               – two-segment numeric             (e.g. 3.13)
#   X.Y-label         – two-segment + alphanumeric tag  (e.g. 3.13-260819)
#   X.Y.Z             – classic semver
#   X.Y.Z-label       – semver with snapshot/label tag  (e.g. 1.2.4-rc1)
#   X.Y.Z.b           – semver with build segment
#   X.Y.Z.b-label     – semver+build with label tag
# The label suffix is alphanumeric only (no further dashes or dots).
SEMVER_BODY = r"[0-9]+\.[0-9]+(?:\.[0-9]+(?:\.[0-9]+)?)?(?:-[a-zA-Z0-9]+)?"
SEMVER_PATTERN = re.compile(rf"^{SEMVER_BODY}$")
SEMVER_TAG_PATTERN = re.compile(rf"^v?({SEMVER_BODY})$")

# Numeric-only semver body: X.Y or X.Y.Z (no build segment, no label)
_SEMVER_NUMERIC = re.compile(r"^[0-9]+\.[0-9]+(?:\.[0-9]+)?$")

# Decomposition regexes for the migration shim and _decompose_version_string
_DECOMP_3 = re.compile(
    r"^([0-9]+)\.([0-9]+)\.([0-9]+)(?:\.([0-9]+))?(?:-([a-zA-Z0-9]+))?$"
)
_DECOMP_2 = re.compile(r"^([0-9]+)\.([0-9]+)(?:-([a-zA-Z0-9]+))?$")


def _decompose_version_string(value: str) -> dict:
    """Decompose a flat version string into a VersionEntry-compatible dict.

    Accepts X.Y, X.Y-label, X.Y.Z, X.Y.Z.b, X.Y.Z-label, X.Y.Z.b-label.
    Raises ValueError when the string does not match any accepted format.
    """
    cleaned = value.strip()
    m3 = _DECOMP_3.match(cleaned)
    m2 = _DECOMP_2.match(cleaned)
    if m3:
        result: dict = {
            "semver": f"{m3.group(1)}.{m3.group(2)}.{m3.group(3)}",
            "build": int(m3.group(4)) if m3.group(4) is not None else None,
            "tag_suffix": m3.group(5),
        }
    elif m2:
        result = {
            "semver": f"{m2.group(1)}.{m2.group(2)}",
            "build": None,
            "tag_suffix": m2.group(3),
        }
    else:
        raise ValueError(f"Cannot decompose version string: {value!r}")
    return result


class VersionEntry(BaseModel):
    """Structured representation of a single version point.

    Fields:
        semver:     Numeric version core — X.Y or X.Y.Z (no build, no label).
        build:      Optional fourth numeric segment (the .b in X.Y.Z.b).
        tag_suffix: Optional alphanumeric label appended after a dash
                    (e.g. 'rc1', '260819').

    Use composed() to reconstruct the full human-readable version string.
    """

    semver: str
    build: int | None = None
    tag_suffix: str | None = None

    @field_validator("semver")
    @classmethod
    def validate_semver(cls, value: str) -> str:
        cleaned = value.strip()
        if not _SEMVER_NUMERIC.fullmatch(cleaned):
            raise ValueError(
                "semver must be a numeric X.Y or X.Y.Z string (no build segment, no label)"
            )
        result = cleaned
        return result

    @field_validator("tag_suffix")
    @classmethod
    def validate_tag_suffix(cls, value: str | None) -> str | None:
        if value is not None and not value.isalnum():
            raise ValueError("tag_suffix must be alphanumeric (letters and digits only)")
        result = value
        return result

    def composed(self) -> str:
        """Return the full version string (e.g. '1.2.3.4-rc1')."""
        base = self.semver
        if self.build is not None:
            base = f"{base}.{self.build}"
        if self.tag_suffix is not None:
            base = f"{base}-{self.tag_suffix}"
        result = base
        return result

    @classmethod
    def from_string(cls, value: str) -> "VersionEntry":
        """Construct a VersionEntry from a flat version string (e.g. '1.2.3-rc1')."""
        result = cls.model_validate(_decompose_version_string(value))
        return result


class Version(BaseModel):
    current: VersionEntry
    previous: VersionEntry | None = None

    @model_validator(mode="before")
    @classmethod
    def migrate_flat_format(cls, data: object) -> object:
        """Accept the legacy flat-string format and decompose into VersionEntry dicts.

        Older version.yml files stored current/previous as plain strings
        (e.g. ``current: '1.2.3'``).  YAML may also parse unquoted numeric values
        like ``3.12`` as a float — this shim normalises both cases to the structured
        VersionEntry mapping so old and new files load cleanly.
        """
        migrated = dict(data) if isinstance(data, dict) else data
        if isinstance(migrated, dict):
            for field in ("current", "previous"):
                value = migrated.get(field)
                if isinstance(value, (str, int, float)):
                    migrated[field] = _decompose_version_string(str(value))
        result = migrated
        return result


class Project(BaseModel):
    name: str
    version: Version
    manifest: Path | None = None

    def __str__(self) -> str:
        result = f"{self.name} v{self.version.current.composed()}"
        return result
