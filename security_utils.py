"""Security helpers for protecting secrets stored in the local database."""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


class SecretCipher:
    """Encrypt and decrypt application secrets using a key derived from configuration."""

    def __init__(self, secret: str):
        if not isinstance(secret, str) or len(secret.strip()) < 32:
            raise ValueError(
                "A strong SECRET_KEY or DESTINATION_ENCRYPTION_KEY (at least 32 characters) is required."
            )

        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
        self._fernet = Fernet(key)

    def encrypt(self, value: str) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError("Secret value cannot be empty.")
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, encrypted_value: str) -> str:
        try:
            return self._fernet.decrypt(encrypted_value.encode("utf-8")).decode("utf-8")
        except (InvalidToken, AttributeError, UnicodeError) as exc:
            raise ValueError("Unable to decrypt the stored destination key.") from exc


def mask_secret(value: str, visible_characters: int = 4) -> str:
    """Return a non-sensitive label that indicates a secret is configured."""
    if not value:
        return ""
    suffix = value[-visible_characters:] if len(value) > visible_characters else ""
    return f"{'•' * 12}{suffix}"


def redact_url(url: str) -> str:
    """Remove query data and user info before a streaming URL is exposed in logs/UI."""
    if not url:
        return ""
    base = url.split("?", 1)[0]
    if "://" in base and "@" in base:
        scheme, remainder = base.split("://", 1)
        base = f"{scheme}://{remainder.split('@', 1)[1]}"
    return base
