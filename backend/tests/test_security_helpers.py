import base64

from cryptography.fernet import Fernet

from services.credential_crypto import decrypt_secret, encrypt_secret, encryption_available, mask_secret, PREFIX
from services.rate_limit import check_rate_limit, reset_rate_limit


def test_credential_crypto_legacy_base64_roundtrip(monkeypatch):
    monkeypatch.delenv("CREDENTIALS_ENCRYPTION_KEY", raising=False)
    encoded = encrypt_secret("secret-value")
    assert encoded == base64.b64encode(b"secret-value").decode()
    assert decrypt_secret(encoded) == "secret-value"
    assert not encryption_available()


def test_credential_crypto_fernet_roundtrip(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", key)
    encoded = encrypt_secret("broker-secret")
    assert encoded.startswith(PREFIX)
    assert "broker-secret" not in encoded
    assert decrypt_secret(encoded) == "broker-secret"
    assert encryption_available()


def test_credential_crypto_missing_key_cannot_decrypt_fernet(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", key)
    encoded = encrypt_secret("broker-secret")
    monkeypatch.delenv("CREDENTIALS_ENCRYPTION_KEY", raising=False)
    assert decrypt_secret(encoded) == ""


def test_mask_secret():
    assert mask_secret("abcdefghi") == "abc****ghi"
    assert mask_secret("abc") == "****"


def test_rate_limit_blocks_after_limit():
    key = "test-rate-limit"
    reset_rate_limit(key)
    assert check_rate_limit(key, limit=2, window_sec=300)
    assert check_rate_limit(key, limit=2, window_sec=300)
    assert not check_rate_limit(key, limit=2, window_sec=300)
    reset_rate_limit(key)
    assert check_rate_limit(key, limit=2, window_sec=300)
