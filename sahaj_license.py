"""
Sahaj License Module — handles activation and local token verification.
"""
import json
import base64

import requests
import machineid
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from PyQt6.QtCore import QSettings

# ============================================================
# CONFIGURATION — YOUR VALUES
# ============================================================
LICENSE_API = "https://sahaj-license-server.nazmul-sahaj.workers.dev"
PUBLIC_KEY_B64 = "NBNVHdiBywMTAIFJWR8EYYok3tHROo4kLR9MnGEjuJQ="

# ============================================================
# INTERNAL HELPERS
# ============================================================
def _get_machine_id():
    """Stable, anonymous hardware fingerprint."""
    return machineid.hashed_id("sahaj-v3")

def _settings():
    return QSettings("NazmulDev", "SahajApp")

def _get_stored_token():
    raw = _settings().value("license/token", "")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None

def _save_token(token):
    s = _settings()
    s.setValue("license/token", json.dumps(token))
    s.sync()  # force write to registry immediately

def _verify_token(token):
    """Verify Ed25519 signature and machine_id."""
    if not token or "payload" not in token or "signature" not in token:
        return False
    try:
        payload_bytes = json.dumps(token["payload"], sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        signature = base64.b64decode(token["signature"])
        public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(PUBLIC_KEY_B64))
        public_key.verify(signature, payload_bytes)
    except Exception:
        return False
    if token["payload"].get("machine_id") != _get_machine_id():
        return False
    return True

# ============================================================
# PUBLIC API
# ============================================================
def is_licensed():
    """Check if the app is licensed on this machine."""
    token = _get_stored_token()
    return _verify_token(token)

def get_licensed_email():
    """Return the buyer's email if the app is licensed, else None."""
    token = _get_stored_token()
    if not _verify_token(token):
        return None
    return token["payload"].get("email", "") or None

def activate(license_key):
    """Contact the server to activate a license key."""
    machine_id_str = _get_machine_id()
    try:
        resp = requests.post(
            f"{LICENSE_API}/activate",
            json={"license_key": license_key, "machine_id": machine_id_str},
            timeout=10,
        )
        data = resp.json()
    except requests.RequestException:
        return False, "Network error. Please check your internet connection."

    if data.get("valid") and data.get("token"):
        _save_token(data["token"])
        return True, "Activated successfully."

    reason = data.get("reason", "")
    if reason == "invalid_key":
        return False, "Invalid license key."
    elif reason == "already_activated":
        return False, "This license is already active on another computer."
    else:
        return False, data.get("message", "Activation failed.")
