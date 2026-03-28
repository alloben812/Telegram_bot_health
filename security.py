"""
Encryption utilities for sensitive data at rest.

Uses Fernet symmetric encryption (AES-128-CBC + HMAC-SHA256).
The encryption key is derived from SECRET_KEY in .env and
is NEVER stored in the database.

Usage:
    from security import encrypt, decrypt

    ciphertext = encrypt("my_password")   # str → str (base64 token)
    plaintext  = decrypt(ciphertext)       # str → str
"""

import base64
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# Salt is fixed and public — security comes from SECRET_KEY, not the salt.
# Changing this value invalidates all existing encrypted data.
_SALT = b"health_bot_v1_salt_2024"


def _build_fernet(secret_key: str) -> Fernet:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_SALT,
        iterations=480_000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(secret_key.encode()))
    return Fernet(key)


def _get_fernet() -> Fernet:
    secret = os.environ.get("SECRET_KEY", "")
    if not secret:
        raise EnvironmentError(
            "SECRET_KEY is not set in .env. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    return _build_fernet(secret)


def encrypt(plaintext: str) -> str:
    """Encrypt a string. Returns a URL-safe base64 Fernet token."""
    if not plaintext:
        return plaintext
    fernet = _get_fernet()
    return fernet.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a Fernet token. Raises ValueError on bad data / wrong key."""
    if not ciphertext:
        return ciphertext
    fernet = _get_fernet()
    try:
        return fernet.decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError(
            "Decryption failed — wrong SECRET_KEY or corrupted data."
        ) from exc


def encrypt_json(data: dict | None) -> str | None:
    """Encrypt a dict serialised as JSON. Returns None if data is None."""
    if data is None:
        return None
    import json
    return encrypt(json.dumps(data))


def decrypt_json(ciphertext: str | None) -> dict | None:
    """Decrypt a JSON-encoded dict. Returns None if ciphertext is None."""
    if ciphertext is None:
        return None
    import json
    return json.loads(decrypt(ciphertext))
