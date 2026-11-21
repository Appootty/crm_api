"""Tells the API which database file to read.
- No VERSIONS_BUCKET / VERSIONS_DIR set: the local file (crm_demo.db), as before.
- Set: the newest published version (named in latest.json), downloaded once and re-checked
  every DB_CHECK_SECONDS (default 120)."""
import json
import os
import tempfile
import threading
import time
from pathlib import Path

from store import configured, open_store

_lock = threading.Lock()
_state = {"checked": 0.0, "file": None, "path": None}
CHECK_SECONDS = int(os.environ.get("DB_CHECK_SECONDS", "120"))


def current_db(default_path: Path) -> Path:
    if not configured("VERSIONS"):
        return default_path
    now = time.time()
    with _lock:
        if _state["path"] and now - _state["checked"] < CHECK_SECONDS:
            return _state["path"]
        _state["checked"] = now
        try:
            store = open_store("VERSIONS")
            meta = store.read_text("latest.json")
            if meta is None:
                if _state["path"]:
                    return _state["path"]
                raise RuntimeError("No database version has been published yet")
            info = json.loads(meta)
            if info["file"] != _state["file"]:
                local = Path(tempfile.gettempdir()) / Path(info["file"]).name
                if not local.exists():
                    store.download(info["file"], local)
                _state["file"], _state["path"] = info["file"], local
        except RuntimeError:
            raise
        except Exception as e:  # network or permission problem: keep serving the last good copy
            if _state["path"]:
                return _state["path"]
            raise RuntimeError(f"Cannot load the database: {e}")
        return _state["path"]


def version_info():
    return {"version": _state["file"]}
