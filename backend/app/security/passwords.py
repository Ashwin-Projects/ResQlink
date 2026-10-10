"""Password hashing: PBKDF2-HMAC-SHA256 from the standard library.

Stored format (also enforced by a CHECK constraint on app_users.password_hash):

    pbkdf2_sha256$<iterations>$<salt, urlsafe base64>$<derived key, urlsafe base64>

The iteration count is stored per hash, so it can be raised later without
invalidating existing accounts (verify_password reads it from the hash).
"""
import base64
import hashlib
import hmac
import secrets

ALGORITHM = "pbkdf2_sha256"
DEFAULT_ITERATIONS = 310_000          # OWASP 2021 recommendation for PBKDF2-HMAC-SHA256
MIN_ITERATIONS = 100_000
SALT_BYTES = 16
KEY_BYTES = 32


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str, *, iterations: int = DEFAULT_ITERATIONS, salt: bytes | None = None) -> str:
    if not isinstance(password, str) or not password:
        raise ValueError("password must be a non-empty string")
    salt = salt if salt is not None else secrets.token_bytes(SALT_BYTES)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=KEY_BYTES)
    return f"{ALGORITHM}${iterations}${_b64(salt)}${_b64(key)}"


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time comparison; any malformed hash simply fails verification."""
    try:
        algorithm, iterations_s, salt_s, key_s = encoded.split("$")
        iterations = int(iterations_s)
        if algorithm != ALGORITHM or iterations < MIN_ITERATIONS:
            return False
        expected = _unb64(key_s)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), _unb64(salt_s), iterations, dklen=len(expected))
    except (ValueError, TypeError, AttributeError):
        return False
    return hmac.compare_digest(actual, expected)


# Used when the username does not exist, so an unknown user costs the same
# PBKDF2 work as a wrong password (no timing oracle for valid usernames).
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def dummy_verify(password: str) -> None:
    verify_password(password, _DUMMY_HASH)
