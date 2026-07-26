"""Filesystem read helpers for per-account config and rate-limit data.

Owns: nothing.
Depends on: stdlib only.
"""

import json
import os
import time
from datetime import datetime


def read_json(path: str):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _iso_to_epoch(iso_str: str | None) -> float:
    try:
        return datetime.fromisoformat(iso_str).timestamp()
    except (TypeError, ValueError):
        return 0


def config_json_paths(config_dir: str) -> list[str]:
    """Candidate paths for Claude Code's main config JSON belonging to `config_dir`.

    Two layouts exist and both must be checked:
      - `<config_dir>/.claude.json` — used when CLAUDE_CONFIG_DIR points at the dir
        (e.g. ~/.claude-personal/.claude.json)
      - `<config_dir>.json` — the default layout, where the config sits *next to*
        the dir rather than inside it (~/.claude -> ~/.claude.json)

    Only checking inside the dir silently loses the default account entirely, which
    is what hid its Fable weekly bar and its email (it fell back to the dir name).
    Note `<config_dir>/claude.json` (no dot) is deliberately not a candidate — Claude
    Code never writes it, and users do keep unrelated files there (e.g. an mcpServers
    snippet) that would shadow the real config.
    """
    return [os.path.join(config_dir, ".claude.json"), f"{config_dir.rstrip('/')}.json"]


def get_scoped_weeklies(config_dir: str) -> list[dict]:
    """Read model-scoped weekly limits (e.g. the Fable-only weekly) from Claude Code's
    cached usage snapshot in the account's config JSON.

    The statusline JSON only carries five_hour/seven_day, so scoped weeklies are
    unavailable via rate-limits.json; this cache is the only on-disk source. Claude
    Code refreshes it infrequently (e.g. when /usage is opened), so each entry keeps
    its own updated_at for staleness display.
    """
    for path in config_json_paths(config_dir):
        cfg = read_json(path)
        cached = (cfg or {}).get("cachedUsageUtilization")
        if not cached:
            continue
        fetched_at = cached.get("fetchedAtMs", 0) / 1000
        now = time.time()
        scoped = []
        for limit in cached.get("utilization", {}).get("limits") or []:
            if limit.get("kind") != "weekly_scoped" or limit.get("percent") is None:
                continue
            resets_at = _iso_to_epoch(limit.get("resets_at"))
            model = (limit.get("scope") or {}).get("model") or {}
            scoped.append(
                {
                    "label": model.get("display_name") or "Scoped",
                    "used_percentage": limit["percent"],
                    "resets_at": resets_at,
                    # Past reset means the cached percent no longer applies; a >6h-old
                    # fetch is flagged too so the UI shows this isn't live data.
                    "is_stale": (now - fetched_at) > 6 * 3600 or resets_at < now,
                    "updated_at": fetched_at,
                }
            )
        if scoped:
            return scoped
    return []


def get_rate_limits(config_dir: str) -> dict | None:
    """Read rate-limits.json written by the statusline capture script."""
    path = os.path.join(config_dir, "rate-limits.json")
    data = read_json(path)
    scoped_weeklies = get_scoped_weeklies(config_dir)
    if not data:
        data = {}

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

    if scoped_weeklies:
        result["scoped_weeklies"] = scoped_weeklies

    if not result:
        return None

    result["updated_at"] = updated_at
    return result


def get_account_email(config_dir: str) -> str:
    for path in config_json_paths(config_dir):
        cfg = read_json(path)
        if cfg and "oauthAccount" in cfg:
            return cfg["oauthAccount"].get("emailAddress", "unknown")
    return os.path.basename(config_dir)
