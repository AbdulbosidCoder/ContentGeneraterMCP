"""Random tokens, hashing and encryption of third-party access tokens at rest."""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from common import config

logger = logging.getLogger("common.security")

_DEV_KEY_SEED = b"content-ai-generator insecure development key"


class ConfigurationError(RuntimeError):
    pass


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """Tokens (sessions, OAuth codes, access tokens) are only ever stored hashed."""
    return hashlib.sha256(token.encode()).hexdigest()


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


@lru_cache(maxsize=2)
def _fernet(key: str | None, meta_real: bool) -> Fernet:
    if key:
        try:
            return Fernet(key.encode())
        except (ValueError, TypeError) as exc:
            raise ConfigurationError(
                "TOKEN_ENCRYPTION_KEY is not a valid Fernet key. Generate one with: "
                "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            ) from exc
    if meta_real:
        raise ConfigurationError(
            "TOKEN_ENCRYPTION_KEY must be set when META_APP_ID/META_APP_SECRET are configured, "
            "because real Facebook tokens are stored encrypted in the database."
        )
    logger.warning("TOKEN_ENCRYPTION_KEY not set: using an insecure development key (mock tokens only).")
    return _dev_fernet()


@lru_cache(maxsize=1)
def _dev_fernet() -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(_DEV_KEY_SEED).digest()))


def cipher() -> Fernet:
    return _fernet(config.env("TOKEN_ENCRYPTION_KEY"), config.meta_configured())


def encrypt(plaintext: str) -> str:
    return cipher().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str, *, is_mock: bool = False) -> str:
    """``is_mock`` also accepts the development key: demo connections created before
    TOKEN_ENCRYPTION_KEY was set were encrypted with it, and their tokens are not secret."""
    try:
        return cipher().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        if is_mock:
            try:
                return _dev_fernet().decrypt(ciphertext.encode()).decode()
            except InvalidToken:
                pass
        raise ConfigurationError(
            "Stored token could not be decrypted; TOKEN_ENCRYPTION_KEY changed. Reconnect the account."
        ) from exc
