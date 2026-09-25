"""Encryption at rest for third-party credentials users hand us.

Users' intervals.icu API keys are full-access credentials to their account,
so store.db only ever holds them encrypted. The Fernet key lives outside the
DB (TOKEN_ENCRYPTION_KEY / config.json `tokenEncryptionKey`); a leaked
store.db alone doesn't expose them.

Generate a key with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

import sys

from cryptography.fernet import Fernet, InvalidToken

from .config import config


def is_configured() -> bool:
    """True only for a usable Fernet key; a malformed one disables the feature."""
    if not config.token_encryption_key:
        return False
    try:
        _fernet()
    except ValueError:
        print("[secret_box] TOKEN_ENCRYPTION_KEY is not a valid Fernet key - intervals.icu step disabled", file=sys.stderr)
        return False
    return True


def _fernet() -> Fernet:
    if not config.token_encryption_key:
        raise ValueError("TOKEN_ENCRYPTION_KEY not configured")
    return Fernet(config.token_encryption_key.encode())


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str | None:
    """None if it can't be decrypted (e.g. the encryption key was rotated)."""
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        return None
