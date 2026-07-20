"""
logger.py — 統一日誌寫入，區分來源。
"""
import os


def log(project_root: str, filename: str, line: str, source: str = "UI"):
    log_dir = os.path.join(project_root, "logs")
    os.makedirs(log_dir, exist_ok=True)
    with open(os.path.join(log_dir, filename), "a", encoding="utf-8") as f:
        f.write("[%s] %s\n" % (source, line))
