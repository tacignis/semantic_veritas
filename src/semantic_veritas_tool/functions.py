# File: src/semantic_veritas_tool/helpers.py
# Author: Jonathan Belden
# Description: Helper functions for the semantic-veritas-tool.


from git import Repo
from pathlib import Path


def save_version(version: str) -> None:
    """
    Saves the version to the version.txt file.
    """
    with open(Path(__file__).parent / "version.txt", "w") as f:
        f.write(version)


def get_version() -> dict[str, str | dict[str, int]]:
    """
    Gets the version from the version.txt file.
    """
    with open(Path(__file__).parent / "version.txt", "r") as f:
        project_info = f.read().split("\n")
        return {
            "project_name": project_info[0],
            "version": __tokenize_version(project_info[1]),
            "previous_version": __tokenize_version(project_info[2]),
        }


def create_git_tag(version: str, message: str) -> None:
    """
    Creates a git tag with the given version and message.
    """
    # TODO: Implement this function for the git repo where the `svt` command is run


def __tokenize_version(version: str) -> dict[str, int]:
    """
    Tokenizes the version string into a dictionary.
    """
    return {
        "major": int(version.split(".")[0]),
        "minor": int(version.split(".")[1]),
        "patch": int(version.split(".")[2]),
    }