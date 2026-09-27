"""Train With GPT MCP Server"""

import importlib.metadata
import os

VERSION_ENV = "TRAIN_WITH_GPT_VERSION"


def app_version() -> str:
    """The release this build is, e.g. "v0.3.1".

    Release tags are the source of truth (RELEASING.md); a build passes its tag
    as the TRAIN_WITH_GPT_VERSION build arg / env var. Without it this is the
    package metadata's placeholder version marked "+dev", never a release name.
    """
    version = os.environ.get(VERSION_ENV, "").strip()
    if version:
        return version
    try:
        return importlib.metadata.version("train-with-gpt") + "+dev"
    except importlib.metadata.PackageNotFoundError:  # a source tree that isn't installed
        return "unknown+dev"


__version__ = app_version()
