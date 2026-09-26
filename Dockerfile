# Runs the HTTP entrypoint (train-with-gpt-http) - the multi-user OAuth path.
# The stdio entrypoint (train-with-gpt, used by Claude Desktop directly) has
# no reason to run in a container.
FROM python:3.14-slim

# git: helpers.py shells out to it for the notes/goals repo.
# openssh-client: needed for git-over-ssh with the deploy key (see
# docker-entrypoint.sh).
RUN apt-get update && apt-get install -y --no-install-recommends git openssh-client \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash app
WORKDIR /app

# Dependencies come from the committed uv.lock, so the image gets exactly the
# versions CI tested. uv is pinned; bump it deliberately.
COPY --from=ghcr.io/astral-sh/uv:0.11.17 /uv /usr/local/bin/uv
# Use the base image's Python (never download one), compile .pyc at build
# time, and install into /app/.venv (on PATH below, so `train-with-gpt-http`
# and `python -c "from train_with_gpt import ..."` work for root and app).
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3 \
    UV_PROJECT_ENVIRONMENT=/app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Dependencies first (only invalidated when the lockfile changes), then the
# project itself as a regular (non-editable) install.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

ENV HOME=/home/app
# Config file, SQLite store (users/tokens/oauth clients), all live here -
# mount a volume at this path to persist across container restarts.
RUN mkdir -p /home/app/.config/train-with-gpt && chown -R app:app /home/app/.config
RUN su app -c 'git config --global user.email "train-with-gpt@container.local" && git config --global user.name "train-with-gpt"'

# Reported by the self_test tool, so a post-deploy check shows which commit is
# live: fly deploy --build-arg GIT_SHA=$(git rev-parse --short HEAD). Late in
# the file so a new SHA doesn't invalidate the dependency layers.
ARG GIT_SHA=unknown
ENV GIT_SHA=$GIT_SHA

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000

# No USER here on purpose: the entrypoint needs root briefly (to chown a
# bind-mounted SSH key into something the `app` user can read) before it
# drops privileges itself - see docker-entrypoint.sh.
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
