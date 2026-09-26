import base64
import binascii
import json
import re
import uuid


MAX_METADATA_BYTES = 8 * 1024
MAX_CIPHERTEXT_BYTES = 50 * 1024 * 1024 + 16
_BASE64URL = re.compile(r"^[A-Za-z0-9_-]+$")


def uuid_value(value):
    if not isinstance(value, str):
        raise ValueError("invalid_uuid")
    parsed = uuid.UUID(value)
    if parsed.version != 4 or str(parsed) != value:
        raise ValueError("invalid_uuid")
    return parsed


def _decoded_size(value):
    if not isinstance(value, str) or not _BASE64URL.fullmatch(value):
        raise ValueError("invalid_encoding")
    try:
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("invalid_encoding") from exc
    if base64.urlsafe_b64encode(raw).decode().rstrip("=") != value:
        raise ValueError("invalid_encoding")
    return len(raw)


def envelope(value, *, wrapped_key=False):
    if not isinstance(value, dict) or set(value) != {"v", "iv", "ct"}:
        raise ValueError("invalid_envelope")
    if type(value["v"]) is not int or value["v"] != 1:
        raise ValueError("invalid_version")
    if not isinstance(value["iv"], str) or not isinstance(value["ct"], str):
        raise ValueError("invalid_encoding")
    if len(json.dumps(value, separators=(",", ":")).encode()) > MAX_METADATA_BYTES:
        raise ValueError("envelope_too_large")
    if _decoded_size(value["iv"]) != 12:
        raise ValueError("invalid_nonce")
    size = _decoded_size(value["ct"])
    if (wrapped_key and size != 48) or (not wrapped_key and size < 16):
        raise ValueError("invalid_ciphertext")
    return value
