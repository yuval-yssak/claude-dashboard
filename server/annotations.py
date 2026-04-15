"""Per-session notes/todos persisted to a single JSON file.

Owns: _annotations dict + _annotations_lock (serialized via atomic-replace write).
Depends on: config (ANNOTATIONS_FILE).

Call load_annotations() once at startup before the cache is built.
"""

import json
import os
import threading

from config import ANNOTATIONS_FILE

_annotations_lock = threading.Lock()
_annotations: dict = {}


def load_annotations():
    global _annotations
    try:
        with open(ANNOTATIONS_FILE) as f:
            _annotations = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        _annotations = {}


def _save_annotations():
    tmp = ANNOTATIONS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(_annotations, f, indent=2)
    os.replace(tmp, ANNOTATIONS_FILE)


def get_annotation(session_id: str) -> dict:
    with _annotations_lock:
        return _annotations.get(session_id, {"notes": "", "todos": []})


def set_annotation(session_id: str, data: dict):
    with _annotations_lock:
        _annotations[session_id] = data
        _save_annotations()
