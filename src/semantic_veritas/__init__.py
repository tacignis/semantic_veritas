from importlib.metadata import PackageNotFoundError, version

_TOOL_PACKAGE_NAME = "semantic-veritas"


def get_tool_version() -> str:
    result: str
    try:
        result = version(_TOOL_PACKAGE_NAME)
    except PackageNotFoundError:
        result = "unknown"
    return result


__version__ = get_tool_version()

from semantic_veritas.semantic_veritas import cli


def main() -> None:
    cli()
