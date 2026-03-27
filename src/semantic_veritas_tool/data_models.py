# File: src/semantic_veritas_tool/data_models.py
# Author: Jonathan Belden
# Description: Data models for the Semantic Veritas Tool


import re
from pathlib import Path

from pydantic import BaseModel, field_validator


SEMVER_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(\.[0-9]+)?$")


class Version(BaseModel):
    current: str
    previous: str | None = None

    @field_validator("current")
    @classmethod
    def validate_current(cls, value: str) -> str:
        cleaned_value = value.strip()
        if not SEMVER_PATTERN.fullmatch(cleaned_value):
            raise ValueError("current version must match X.Y.Z[.b]")
        return cleaned_value

    @field_validator("previous")
    @classmethod
    def validate_previous(cls, value: str | None) -> str | None:
        if value is None:
            validated_value = None
        else:
            cleaned_value = value.strip()
            if not SEMVER_PATTERN.fullmatch(cleaned_value):
                raise ValueError("previous version must match X.Y.Z[.b]")
            validated_value = cleaned_value
        return validated_value


class Project(BaseModel):
    name: str
    version: Version
    manifest: Path | None = None

    def __str__(self) -> str:
        result = f"{self.name} v{self.version.current}"
        return result
        