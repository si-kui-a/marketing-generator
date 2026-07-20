"""
config_loader.py — 讀取設定並強制檢查遷移安全狀態。
啟動流程的唯一入口，任何啟動都會經過此函式，不依賴 AI 是否記得檢查。
"""
import os
import yaml
from migration_tracker import MigrationTracker


def _merge_default_and_local(project_root):
    default_path = os.path.join(project_root, "config.default.yaml")
    if not os.path.isfile(default_path):
        raise FileNotFoundError(
            "config.default.yaml 不存在，拒絕啟動。這不是可忽略的警告——"
            "系統需要明確的預設設定才能安全運作。"
        )
    with open(default_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    local_path = os.path.join(project_root, "your-extensions", "config.local.yaml")
    if os.path.isfile(local_path):
        with open(local_path, "r", encoding="utf-8") as f:
            local = yaml.safe_load(f) or {}
        config.update(local)  # 淺層覆蓋；深層合併留待實際需要巢狀覆蓋時再擴充
    return config


def load_config(project_root: str, allow_degraded_start: bool = False) -> dict:
    config = _merge_default_and_local(project_root)
    tracker = MigrationTracker(project_root)
    unverified = tracker.list_unverified()
    if unverified:
        if not allow_degraded_start:
            raise RuntimeError(
                "❌ 啟動中止：以下路徑處於 'moved 但未 verified' 的中間狀態，"
                "代表上次遷移流程中斷於危險節點，必須先完成驗證：%s\n"
                "請執行 safe_git.mark_verified(path, note='具體驗證描述') 後再啟動。\n"
                "如需緊急啟動處理無關事務，設定環境變數 ALLOW_DEGRADED_START=1，"
                "但屆時所有寫入操作將被鎖定為唯讀。" % unverified
            )
        else:
            config["_degraded_mode"] = True
            config["_degraded_reason"] = unverified
            print("⚠️⚠️⚠️ 降級模式啟動中：%s 尚未驗證，所有寫入操作已停用，"
                  "請盡速完成遷移驗證。" % unverified)
    version_file = os.path.join(project_root, "local_kit", "VERSION")
    if os.path.exists(version_file):
        with open(version_file, "r", encoding="utf-8") as f:
            print("ℹ️ local_kit version: %s（如需更新請執行 scripts/sync_local_kit.sh）"
                  % f.read().strip())
    return config
