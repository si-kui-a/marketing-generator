"""
migration_tracker.py — 追蹤批次格式遷移的狀態，取代人工記憶。
"""
import json
import os
from datetime import datetime


class MigrationTracker:
    def __init__(self, project_root: str):
        self.file = os.path.join(project_root, "MIGRATION_STATUS.json")

    def _load(self):
        if not os.path.isfile(self.file):
            return {}
        with open(self.file, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except ValueError:
                return {}

    def _save(self, data):
        with open(self.file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def record(self, path: str, status: str, note: str = ""):
        data = self._load()
        entry = data.setdefault(path, {"history": []})
        entry["history"].append({
            "status": status, "note": note,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        })
        self._save(data)

    def get_status(self, path: str):
        data = self._load()
        history = data.get(path, {}).get("history", [])
        return history[-1]["status"] if history else None

    def list_pending_purge(self):
        data = self._load()
        return [p for p, e in data.items()
                if e["history"] and e["history"][-1]["status"] == "verified"]

    def list_unverified(self):
        data = self._load()
        return [p for p, e in data.items()
                if e["history"] and e["history"][-1]["status"] == "moved"]
