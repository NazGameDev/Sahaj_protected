"""
Sahaj License Module — handles activation and local token verification.

Robustness features:
  * Ed25519 signed tokens (server-signed, app-verified)
  * JSON serialization matches JavaScript exactly (sorted keys, no spaces, UTF-8)
  * Token is stored in BOTH QSettings (registry) AND a file backup
    in %LOCALAPPDATA%\\Sahaj_v1_1\\license.dat — so a registry cleaner
    cannot lock the user out.
"""
import os
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


def _token_backup_path():
    """Path to the file-based token backup (survives registry cleaning)."""
    appdata = os.environ.get('LOCALAPPDATA', os.path.expanduser('~'))
    app_dir = os.path.join(appdata, 'Sahaj_v1_1')
    os.makedirs(app_dir, exist_ok=True)
    return os.path.join(app_dir, 'license.dat')


def _get_stored_token():
    """Read the saved activation token.

    Tries QSettings first (fast), then the file backup (survives
    CCleaner / registry cleanups). If the file backup is used, the
    token is silently restored to QSettings for future reads.
    """
    # 1. Try QSettings
    raw = _settings().value("license/token", "")
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass  # corrupted, fall through to file backup

    # 2. Fallback: file backup
    try:
        backup = _token_backup_path()
        if os.path.exists(backup):
            with open(backup, "r", encoding="utf-8") as f:
                token = json.load(f)
            # Restore to QSettings so future reads are fast
            s = _settings()
            s.setValue("license/token", json.dumps(token))
            s.sync()
            return token
    except Exception:
        pass

    return None


def _save_token(token):
    """Save the activation token to both QSettings and file backup."""
    # 1. QSettings (registry)
    s = _settings()
    s.setValue("license/token", json.dumps(token))
    s.sync()  # force write to registry immediately

    # 2. File backup (survives registry cleaning)
    try:
        with open(_token_backup_path(), "w", encoding="utf-8") as f:
            json.dump(token, f)
    except Exception:
        pass


def _verify_token(token):
    """Verify Ed25519 signature and machine_id."""
    if not token or "payload" not in token or "signature" not in token:
        return False
    try:
        # Must match the JavaScript side exactly:
        #   - keys sorted alphabetically
        #   - no spaces after ':' or ','
        #   - UTF-8 bytes (no ASCII escaping)
        payload_bytes = json.dumps(
            token["payload"],
            sort_keys=True,
            separators=(',', ':'),
            ensure_ascii=False,
        ).encode('utf-8')

        signature = base64.b64decode(token["signature"])
        public_key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(PUBLIC_KEY_B64)
        )
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
    """Contact the server to activate a license key.

    Returns (success: bool, message: str).
    """
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
