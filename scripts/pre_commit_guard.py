"""
pre_commit_guard.py — git commit前的強制檢查，安裝於 .git/hooks/pre-commit。
"""
import subprocess
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "local_kit"))


def main():
    repo_root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True
    ).stdout.strip()
    tracker_file = os.path.join(repo_root, "MIGRATION_STATUS.json")
    if not os.path.isfile(tracker_file):
        sys.exit(0)  # 未啟用批次遷移保護，直接放行

    from migration_tracker import MigrationTracker
    tracker = MigrationTracker(repo_root)

    result = subprocess.run(
        ["git", "diff", "--cached", "--name-status"],
        cwd=repo_root, capture_output=True, text=True
    )
    deleted_files = [
        line.split("\t", 1)[1] for line in result.stdout.strip().splitlines()
        if line.startswith("D\t")
    ]
    for f in deleted_files:
        # 反查所屬path（去除_deprecated後綴與檔名部分，抓目錄層級）
        for candidate in tracker._load().keys():
            if f.startswith(candidate + "_deprecated") or f.startswith(candidate):
                status = tracker.get_status(candidate)
                if status != "verified":
                    print(
                        "❌ 阻擋commit：偵測到刪除 %s，但 migration_tracker 中狀態為 %s"
                        "（需為 verified）。請先執行 mark_verified() 並提供具體驗證說明，"
                        "或此操作不應包含在本次commit中。" % (f, status)
                    )
                    sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
