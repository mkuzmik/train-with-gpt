"""Hermetic environment shared by unit and integration tests.

Guarantees, for every test:
- HOME points at a throwaway directory, so neither the real
  ~/.config/train-with-gpt/config.json nor ~/.config/train-with-gpt/store.db
  is ever read or written. This is set up *before* train_with_gpt is imported,
  because config.py loads its global `config` at import time.
- Config env vars (INTERVALS_API_KEY, STRAVA_CLIENT_ID, TRAINING_REPO_PATH, ...)
  and every GIT_* var are scrubbed; git gets a fixed identity and no
  user/system gitconfig.
- The global `config` starts empty, and its file plus the SQLite store live in
  the test's own tmp dir. Tests opt in to credentials via fixtures.
- No real network: all httpx traffic goes through a respx router
  (`http_mock`) that fails on any unstubbed request, and non-loopback socket
  connects raise.
"""

import os
import shutil
import socket
import tempfile
from pathlib import Path

# --- Must run before anything imports train_with_gpt -----------------------

_SCRUBBED_ENV = (
    "INTERVALS_API_KEY",
    "TRAINING_REPO_PATH",
    "TRAINING_REPO_URL",
    "TRAINING_CONTEXT_DEPLOY_KEY",
    "STRAVA_CLIENT_ID",
    "STRAVA_CLIENT_SECRET",
    "TOKEN_ENCRYPTION_KEY",
    "PUBLIC_URL",
    "PORT",
)
for _name in list(os.environ):
    if _name in _SCRUBBED_ENV or _name.startswith("GIT_"):
        del os.environ[_name]

_SESSION_HOME = Path(tempfile.mkdtemp(prefix="twg-tests-home-"))
os.environ["HOME"] = str(_SESSION_HOME)
os.environ["XDG_CONFIG_HOME"] = str(_SESSION_HOME / ".config")
os.environ.update(
    GIT_AUTHOR_NAME="Test Runner",
    GIT_AUTHOR_EMAIL="tests@example.invalid",
    GIT_COMMITTER_NAME="Test Runner",
    GIT_COMMITTER_EMAIL="tests@example.invalid",
    GIT_CONFIG_NOSYSTEM="1",
    GIT_TERMINAL_PROMPT="0",
)

# ---------------------------------------------------------------------------

import pytest  # noqa: E402
import respx  # noqa: E402
from cryptography.fernet import Fernet  # noqa: E402

from train_with_gpt import config as config_module  # noqa: E402
from train_with_gpt import store  # noqa: E402
from train_with_gpt.config import config as app_config  # noqa: E402

from tests.support import (  # noqa: E402
    INTERVALS_API_KEY,
    STRAVA_CLIENT_ID,
    STRAVA_CLIENT_SECRET,
    clone,
    make_bare_remote,
)


def pytest_configure(config):
    config.addinivalue_line("markers", "unit: fast, in-process tests of single modules (tests/unit)")
    config.addinivalue_line("markers", "integration: black-box tests through the app's public interfaces (tests/integration)")


def pytest_collection_modifyitems(config, items):
    tests_dir = Path(__file__).parent
    for item in items:
        try:
            level = item.path.relative_to(tests_dir).parts[0]
        except ValueError:
            continue
        if level in ("unit", "integration"):
            item.add_marker(getattr(pytest.mark, level))


def pytest_unconfigure(config):
    shutil.rmtree(_SESSION_HOME, ignore_errors=True)


_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def _check_address(sock, address):
    if sock.family in (socket.AF_INET, socket.AF_INET6) and address[0] not in _LOOPBACK:
        raise RuntimeError(f"Tests must not touch the network (tried to connect to {address!r})")


def _guarded_connect(self, address):
    _check_address(self, address)
    return _real_connect(self, address)


def _guarded_connect_ex(self, address):
    _check_address(self, address)
    return _real_connect_ex(self, address)


@pytest.fixture(autouse=True)
def hermetic(tmp_path, monkeypatch):
    """Per-test HOME, config file, store DB and an empty global config."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))

    config_dir = home / ".config" / "train-with-gpt"
    monkeypatch.setattr(config_module, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(config_module, "CONFIG_FILE", config_dir / "config.json")
    monkeypatch.setattr(app_config, "config_file", config_dir / "config.json")
    monkeypatch.setattr(store, "DB_PATH", config_dir / "store.db")

    for attr in ("intervals_api_key", "training_repo_path", "client_id", "client_secret", "token_encryption_key"):
        monkeypatch.setattr(app_config, attr, None)

    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _guarded_connect_ex)
    return home


@pytest.fixture(autouse=True)
def http_mock():
    """respx router for all outgoing httpx traffic; unstubbed requests fail."""
    with respx.mock(assert_all_mocked=True, assert_all_called=False) as router:
        yield router


@pytest.fixture
def db():
    """An initialised store in the test's tmp HOME; returns its path."""
    store.init_db()
    return store.DB_PATH


@pytest.fixture
def strava_app_credentials(monkeypatch):
    """This server's own Strava app credentials (client_id/secret)."""
    monkeypatch.setattr(app_config, "client_id", STRAVA_CLIENT_ID)
    monkeypatch.setattr(app_config, "client_secret", STRAVA_CLIENT_SECRET)


@pytest.fixture
def token_encryption_key(monkeypatch):
    """A fresh Fernet key, which turns on the optional intervals.icu login step."""
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(app_config, "token_encryption_key", key)
    return key


@pytest.fixture
def intervals_api_key(monkeypatch):
    """A (fake) personal intervals.icu API key."""
    monkeypatch.setattr(app_config, "intervals_api_key", INTERVALS_API_KEY)
    return INTERVALS_API_KEY


@pytest.fixture(scope="session")
def _seeded_remote_template(tmp_path_factory):
    return make_bare_remote(tmp_path_factory.mktemp("template") / "training-context.git")


@pytest.fixture
def git_remote(_seeded_remote_template, tmp_path):
    """A local bare repo (branch main, one initial commit) standing in for the
    training-context repo's remote. Each test gets its own copy."""
    return Path(shutil.copytree(_seeded_remote_template, tmp_path / "training-context.git"))


@pytest.fixture
def training_repo(git_remote, tmp_path, monkeypatch):
    """A clone of `git_remote`, configured as the training repo; returns its path."""
    repo = clone(git_remote, tmp_path / "training-context")
    monkeypatch.setattr(app_config, "training_repo_path", str(repo))
    return repo
