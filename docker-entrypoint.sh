#!/bin/sh
# Runs as root (see Dockerfile - no USER before this), because a bind-mounted
# SSH key is owned by the host user's UID, not the container's `app` user,
# so app can't read it directly even at mode 600. This script copies it into
# a location app owns with the right permissions, clones the training-context
# repo if it isn't already there, then drops privileges to app for the
# actual server process.
set -e

SSH_DIR=/home/app/.ssh

# Platform volumes (e.g. Fly) mount root-owned; the store lives here.
chown app:app /home/app/.config/train-with-gpt
DEPLOY_KEY_SRC=/run/secrets/training_context_deploy_key
REPO_DIR="${TRAINING_REPO_PATH:-/data/training-context}"
REPO_URL="${TRAINING_REPO_URL:-}"

# Platforms without file secrets (e.g. Fly.io) pass the key text as an env var.
if [ ! -f "$DEPLOY_KEY_SRC" ] && [ -n "${TRAINING_CONTEXT_DEPLOY_KEY:-}" ]; then
    DEPLOY_KEY_SRC=/tmp/deploy_key_from_env
    (umask 077; printf '%s\n' "$TRAINING_CONTEXT_DEPLOY_KEY" > "$DEPLOY_KEY_SRC")
fi

if [ -f "$DEPLOY_KEY_SRC" ]; then
    mkdir -p "$SSH_DIR"
    cp "$DEPLOY_KEY_SRC" "$SSH_DIR/deploy_key"
    case "$DEPLOY_KEY_SRC" in /tmp/*) rm -f "$DEPLOY_KEY_SRC" ;; esac
    chmod 600 "$SSH_DIR/deploy_key"
    ssh-keyscan -t ed25519 github.com > "$SSH_DIR/known_hosts" 2>/dev/null
    chown -R app:app "$SSH_DIR"

    export GIT_SSH_COMMAND="ssh -i $SSH_DIR/deploy_key -o UserKnownHostsFile=$SSH_DIR/known_hosts -o IdentitiesOnly=yes"

    mkdir -p "$REPO_DIR"
    chown -R app:app "$REPO_DIR"
    if [ -n "$REPO_URL" ] && [ ! -d "$REPO_DIR/.git" ]; then
        echo "[entrypoint] Cloning $REPO_URL into $REPO_DIR" >&2
        su app -c "GIT_SSH_COMMAND='$GIT_SSH_COMMAND' git clone '$REPO_URL' '$REPO_DIR'"
    fi
else
    echo "[entrypoint] No deploy key mounted at $DEPLOY_KEY_SRC - notes/goals git operations will report 'no remote configured' if TRAINING_REPO_PATH is used without a repo already cloned there." >&2
fi

unset TRAINING_CONTEXT_DEPLOY_KEY
exec su app -c "GIT_SSH_COMMAND='$GIT_SSH_COMMAND' exec train-with-gpt-http"
