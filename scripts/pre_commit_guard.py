"""
pre_commit_guard.py — git commit前的強制檢查，安裝於 .git/hooks/pre-commit。
"""
import subprocess
import sys
import os

# Windows 主控台預設編碼(如 cp950)無法輸出中文/emoji,強制 stdout/stderr 走 UTF-8。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "local_kit"))


def main():
    # encoding 必須明確指定 utf-8:git 輸出含中文檔名時,text=True 若不指定 encoding
    # 會在背景 reader thread 拋出 UnicodeDecodeError,導致 stdout 靜默變 None,
    # hook 因此以未捕捉例外崩潰、非零結束碼阻擋commit(見專案事故記錄)。
    repo_root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, encoding="utf-8"
    ).stdout.strip()
    tracker_file = os.path.join(repo_root, "MIGRATION_STATUS.json")
    if not os.path.isfile(tracker_file):
        sys.exit(0)  # 未啟用批次遷移保護，直接放行

    from migration_tracker import MigrationTracker
    tracker = MigrationTracker(repo_root)

    result = subprocess.run(
        ["git", "diff", "--cached", "--name-status"],
        cwd=repo_root, capture_output=True, text=True, encoding="utf-8"
    )
    deleted_files = [
        line.split("\t", 1)[1] for line in result.stdout.strip().splitlines()
        if line.startswith("D\t")
    ]
    # "purged" 也視為已授權:safe_git.purge_deprecated() 自身已在動作前檢查
    # current == "verified" 才允許執行(見 safe_git.py),且會在呼叫 git commit
    # 之前就把 tracker 狀態寫成 "purged"——若此處仍要求 "verified" 才放行,
    # 會變成 purge_deprecated() 自己產生的、本該合法的 commit 反被此 hook 擋下
    # (雞生蛋蛋生雞:committing的當下磁碟上狀態已經是purged,而非verified)。
    ALLOWED_STATUSES = ("verified", "purged")
    for f in deleted_files:
        # 反查所屬path（去除_deprecated後綴與檔名部分，抓目錄層級）
        for candidate in tracker._load().keys():
            if f.startswith(candidate + "_deprecated") or f.startswith(candidate):
                status = tracker.get_status(candidate)
                if status not in ALLOWED_STATUSES:
                    print(
                        "❌ 阻擋commit：偵測到刪除 %s，但 migration_tracker 中狀態為 %s"
                        "（需為 verified 或 purged）。請先執行 mark_verified() 並提供具體驗證說明，"
                        "或此操作不應包含在本次commit中。" % (f, status)
                    )
                    sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
