"""Tests for security.py — encryption/decryption."""

from __future__ import annotations

import os
import pytest
from security import encrypt, decrypt, encrypt_json, decrypt_json, _build_fernet


class TestEncryptDecrypt:
    def test_roundtrip(self):
        plaintext = "my_secret_password"
        ciphertext = encrypt(plaintext)
        assert ciphertext != plaintext
        assert decrypt(ciphertext) == plaintext

    def test_roundtrip_unicode(self):
        plaintext = "пароль_юникод_🔑"
        assert decrypt(encrypt(plaintext)) == plaintext

    def test_empty_string_passthrough(self):
        assert encrypt("") == ""
        assert decrypt("") == ""

    def test_decrypt_wrong_key_raises(self):
        ciphertext = encrypt("secret")
        # Build a fernet with a different key
        other_fernet = _build_fernet("b" * 64)
        bad_ciphertext = other_fernet.encrypt(b"other").decode()
        with pytest.raises(ValueError, match="Decryption failed"):
            decrypt(bad_ciphertext)

    def test_decrypt_garbage_raises(self):
        with pytest.raises(ValueError):
            decrypt("not-a-valid-fernet-token")


class TestEncryptDecryptJson:
    def test_roundtrip(self):
        data = {"access_token": "abc123", "refresh_token": "xyz789", "expires_in": 3600}
        ciphertext = encrypt_json(data)
        assert isinstance(ciphertext, str)
        assert decrypt_json(ciphertext) == data

    def test_none_passthrough(self):
        assert encrypt_json(None) is None
        assert decrypt_json(None) is None

    def test_nested_dict(self):
        data = {"user": {"name": "test", "scores": [1, 2, 3]}}
        assert decrypt_json(encrypt_json(data)) == data
