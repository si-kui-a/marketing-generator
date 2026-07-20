"""
safe_git.py — 批次格式遷移的安全操作集合。
僅用於「結構性遷移」（如整個資料夾轉檔），不用於日常單筆CRUD刪除。
"""
import os
import subprocess
from migration_tracker import MigrationTracker


def _run(args, cwd, check=True):
    # encoding 必須明確指定 utf-8:Windows 主控台預設編碼(如 cp950)無法解碼
    # git 輸出的中文檔名,text=True 若不指定 encoding 會在背景 reader thread
    # 拋出 UnicodeDecodeError,導致 stdout 靜默變成 None(見專案事故記錄)。
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    if check and r.returncode != 0:
        raise RuntimeError("指令失敗 %s：%s" % (args, r.stderr.strip()))
    return r


def safe_commit(message: str, allowed_scope: list, project_root: str):
    staged = _run(["git", "diff", "--cached", "--name-only"], project_root).stdout.strip().splitlines()

    def normalize(p):
        return p.replace("\\", "/")

    scopes = [normalize(s).rstrip("/") + "/" for s in allowed_scope]
    exact_scopes = set(normalize(s) for s in allowed_scope)
    out_of_scope = []
    for f in staged:
        f_norm = normalize(f)
        if f_norm in exact_scopes:
            continue
        if any(f_norm.startswith(s) for s in scopes):
            continue
        out_of_scope.append(f_norm)
    if out_of_scope:
        raise PermissionError(
            "❌ commit範圍超出宣告：%s\n允許範圍：%s\n"
            "請拆分為獨立commit，或確認這些檔案是否真的該包含在本次意圖內。"
            % (out_of_scope, allowed_scope)
        )
    _run(["git", "commit", "-m", message], project_root)


def safe_delete(path: str, project_root: str):
    status = _run(["git", "status", "--short"], project_root).stdout.strip()
    if status:
        raise RuntimeError("git status 非 clean，中止遷移，請先處理以下未提交異動：\n%s" % status)
    full_src = os.path.join(project_root, path)
    full_dst = os.path.join(project_root, path + "_deprecated")
    _run(["git", "mv", full_src, full_dst], project_root)
    tracker = MigrationTracker(project_root)
    tracker.record(path, "moved", "git mv %s -> %s_deprecated" % (path, path))
    _run(["git", "add", "MIGRATION_STATUS.json"], project_root)
    safe_commit(
        "migrate: mv %s to deprecated [1/3]" % path,
        allowed_scope=[path, path + "_deprecated", "MIGRATION_STATUS.json"],
        project_root=project_root,
    )


def mark_verified(path: str, project_root: str, note: str):
    if not note or not note.strip():
        raise ValueError("note 不可為空，必須提供具體驗證描述")
    tracker = MigrationTracker(project_root)
    current = tracker.get_status(path)
    if current != "moved":
        raise RuntimeError(
            "此路徑目前狀態為 %s，無法標記為verified，請檢查流程順序" % current
        )
    tracker.record(path, "verified", note)


def purge_deprecated(path: str, project_root: str, interactive: bool = True):
    tracker = MigrationTracker(project_root)
    current = tracker.get_status(path)
    if current != "verified":
        raise PermissionError(
            "此路徑狀態為 %s，未通過verified，禁止purge。"
            "這是硬性阻擋，防止重蹈資料誤刪事故。" % current
        )
    dep_path = path + "_deprecated"
    print("即將永久刪除以下路徑：%s" % dep_path)
    if interactive:
        confirm = input("確認刪除以上檔案？[yes/N] ")
        if confirm.strip().lower() != "yes":
            print("已取消")
            return
    _run(["git", "rm", "-r", os.path.join(project_root, dep_path)], project_root)
    tracker.record(path, "purged", "")
    _run(["git", "add", "MIGRATION_STATUS.json"], project_root)
    safe_commit(
        "migrate: purge %s [3/3]" % dep_path,
        allowed_scope=[dep_path, "MIGRATION_STATUS.json"],
        project_root=project_root,
    )


def rollback_migration(path: str, reason: str, project_root: str):
    if not reason or not reason.strip():
        raise ValueError("reason 不可為空")
    tracker = MigrationTracker(project_root)
    current = tracker.get_status(path)
    if current != "moved":
        raise PermissionError(
            "此路徑狀態為 %s，僅 'moved' 狀態可rollback。"
            "若已verified才發現問題，需走人工re_migrate流程（見文件說明），"
            "不提供自動化撤銷。" % current
        )
    full_dep = os.path.join(project_root, path + "_deprecated")
    full_orig = os.path.join(project_root, path)
    _run(["git", "mv", full_dep, full_orig], project_root)
    tracker.record(path, "rolled_back", reason)
    _run(["git", "add", "MIGRATION_STATUS.json"], project_root)
    safe_commit(
        "migrate: rollback %s - %s [aborted]" % (path, reason),
        allowed_scope=[path, path + "_deprecated", "MIGRATION_STATUS.json"],
        project_root=project_root,
    )
