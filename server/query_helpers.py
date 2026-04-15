"""Filesystem read helpers for per-account config and rate-limit data.

Owns: nothing.
Depends on: stdlib only.
"""

import json
import os
import time


def read_json(path: str):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def get_rate_limits(config_dir: str) -> dict | None:
    """Read rate-limits.json written by the statusline capture script."""
    path = os.path.join(config_dir, "rate-limits.json")
    data = read_json(path)
    if not data:
        return None

    now = time.time()
    updated_at = data.get("updated_at", 0)
    # Data older than 6 hours is stale (five_hour window is 5h, so 6h guarantees expiry)
    age_stale = (now - updated_at) > 6 * 3600

    result = {}
    for key in ("five_hour", "seven_day"):
        entry = data.get(key)
        if entry:
            resets_at = entry.get("resets_at", 0)
            result[key] = {
                "used_percentage": entry.get("used_percentage", 0),
                "resets_at": resets_at,
                "is_stale": age_stale or resets_at < now,
            }

    if not result:
        return None

    result["updated_at"] = updated_at
    return result


def get_account_email(config_dir: str) -> str:
    # Try both possible config filenames
    for name in ("claude.json", ".claude.json"):
        cfg = read_json(os.path.join(config_dir, name))
        if cfg and "oauthAccount" in cfg:
            return cfg["oauthAccount"].get("emailAddress", "unknown")
    return os.path.basename(config_dir)
