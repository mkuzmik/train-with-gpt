#!/bin/sh
# Runs as root (see Dockerfile - no USER before this), because a bind-mounted
# SSH key is owned by the host user's UID, not the container's `app` user,
# so app can't read it directly even at mode 600. This script copies it into
# a location app owns with the right permissions, clones the training-context
# repo if it isn't already there, then drops privileges to app for the
# actual server process.
set -e

SSH_DIR=/home/app/.ssh
CONFIG_DIR=/home/app/.config/train-with-gpt

# GitHub's published ed25519 host key (https://api.github.com/meta, "ssh_keys").
# Pinned rather than fetched with ssh-keyscan at boot, so a network MITM during
# startup can't get its own key trusted for the write-enabled deploy key.
GITHUB_HOST_KEY="github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"

# Platform volumes (e.g. Fly) mount root-owned; the store lives here.
chown app:app "$CONFIG_DIR"

# docker-compose mounts config.json as a secret owned by the host UID (mode
# 600), which app can't read unless the UIDs happen to match. Root can, so copy
# it into app's own config dir with the right ownership.
CONFIG_SRC=/run/secrets/train_with_gpt_config
if [ -f "$CONFIG_SRC" ]; then
    cp "$CONFIG_SRC" "$CONFIG_DIR/config.json"
    chown app:app "$CONFIG_DIR/config.json"
    chmod 600 "$CONFIG_DIR/config.json"
fi
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
    printf '%s\n' "$GITHUB_HOST_KEY" > "$SSH_DIR/known_hosts"
    chown -R app:app "$SSH_DIR"

    export GIT_SSH_COMMAND="ssh -i $SSH_DIR/deploy_key -o UserKnownHostsFile=$SSH_DIR/known_hosts -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes"

    # Also as app's git default, so commands run later over `fly ssh console`
    # (e.g. su app -c 'train-with-gpt-selftest ...') can fetch/push without
    # repeating this line.
    su app -c "git config --global core.sshCommand '$GIT_SSH_COMMAND'"

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
