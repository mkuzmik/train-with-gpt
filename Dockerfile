# Runs the HTTP entrypoint (train-with-gpt-http) - the multi-user OAuth path.
# The stdio entrypoint (train-with-gpt, used by Claude Desktop directly) has
# no reason to run in a container.
FROM python:3.12-slim

# git: helpers.py shells out to it for the notes/goals repo.
# openssh-client: needed for git-over-ssh with the deploy key (see
# docker-entrypoint.sh).
RUN apt-get update && apt-get install -y --no-install-recommends git openssh-client \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash app
WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

ENV HOME=/home/app
# Config file, SQLite store (users/tokens/oauth clients), all live here -
# mount a volume at this path to persist across container restarts.
RUN mkdir -p /home/app/.config/train-with-gpt && chown -R app:app /home/app/.config
RUN su app -c 'git config --global user.email "train-with-gpt@container.local" && git config --global user.name "train-with-gpt"'

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000

# No USER here on purpose: the entrypoint needs root briefly (to chown a
# bind-mounted SSH key into something the `app` user can read) before it
# drops privileges itself - see docker-entrypoint.sh.
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
