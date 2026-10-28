"""Bounded password verification and transparent upgrades of old records."""
import base64
import hashlib
import hmac
import secrets

PBKDF2_PREFIX = 'pbkdf2_sha256'
PBKDF2_ITERS = 600_000


def hash_password(password, iterations=PBKDF2_ITERS):
    if not 1 <= iterations <= 2_000_000:
        raise ValueError('Invalid password work factor')
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iterations)
    return f'{PBKDF2_PREFIX}${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}'


def verify_password(password, stored):
    if not isinstance(stored, str) or not stored:
        return False
    if not stored.startswith(PBKDF2_PREFIX + '$'):
        return hmac.compare_digest(password.encode('utf-8'), stored.encode('utf-8'))
    try:
        _, count, salt, expected = stored.split('$')
        count = int(count)
        salt = base64.b64decode(salt, validate=True)
        expected = base64.b64decode(expected, validate=True)
        if not 1 <= count <= 2_000_000 or len(salt) != 16 or len(expected) != 32:
            return False
        actual = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, count)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def maybe_upgrade_legacy_password(connection, login, stored, password):
    # Caller has already verified the password. CAS preserves a concurrent reset.
    legacy = not stored.startswith(PBKDF2_PREFIX + '$')
    if legacy or int(stored.split('$')[1]) < PBKDF2_ITERS:
        connection.execute('UPDATE users SET password=? WHERE login=? AND password=?',
                           (hash_password(password), login, stored))
