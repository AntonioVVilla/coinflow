"""Tests for encryption + auth."""
from bot.security import encrypt, decrypt
from bot.auth import hash_password, verify_password


def test_encrypt_decrypt_roundtrip():
    plaintext = "my-secret-api-key-123"
    ciphertext = encrypt(plaintext)
    assert ciphertext != plaintext
    assert decrypt(ciphertext) == plaintext


def test_encrypt_produces_different_output_each_time():
    plain = "same-value"
    c1 = encrypt(plain)
    c2 = encrypt(plain)
    # Fernet includes a random IV, so outputs differ
    assert c1 != c2
    assert decrypt(c1) == decrypt(c2) == plain


def test_password_hash_verify_roundtrip():
    pw = "my-strong-password"
    hashed = hash_password(pw)
    assert hashed != pw
    assert "$" in hashed  # salt$hash format
    assert verify_password(pw, hashed) is True
    assert verify_password("wrong", hashed) is False


def test_password_hash_uses_unique_salts():
    pw = "same-password"
    h1 = hash_password(pw)
    h2 = hash_password(pw)
    assert h1 != h2
    assert verify_password(pw, h1)
    assert verify_password(pw, h2)


def test_verify_password_handles_malformed_hash():
    assert verify_password("test", "") is False
    assert verify_password("test", "no-dollar-sign") is False
