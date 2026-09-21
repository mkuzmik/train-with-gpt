# Runs the HTTP entrypoint (train-with-gpt-http) - the multi-user OAuth path.
# The stdio entrypoint (train-with-gpt, used by Claude Desktop directly) has
# no reason to run in a container.
FROM python:3.12-slim

# git is a runtime dependency: helpers.py shells out to it for the
# notes/goals repo (git pull / add / commit / push).
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash app
WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

USER app
ENV HOME=/home/app
# Config file, SQLite store (users/tokens/oauth clients), all live here -
# mount a volume at this path to persist across container restarts.
RUN mkdir -p /home/app/.config/train-with-gpt
# Needed for `git commit` if the notes/goals repo volume is mounted (see
# docker-compose.yml) - harmless otherwise.
RUN git config --global user.email "train-with-gpt@container.local" \
    && git config --global user.name "train-with-gpt"

EXPOSE 8000

CMD ["train-with-gpt-http"]
