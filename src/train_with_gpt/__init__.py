"""Train With GPT MCP Server"""

import importlib.metadata

# pyproject.toml is the single source of truth for the version (RELEASING.md).
try:
    __version__ = importlib.metadata.version("train-with-gpt")
except importlib.metadata.PackageNotFoundError:  # running from a source tree without installing
    __version__ = "unknown"
