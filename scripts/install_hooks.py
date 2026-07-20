"""
install_hooks.py — 跨OS安裝 pre-commit hook。兩專案各執行一次。
"""
import os
import stat
import shutil
import subprocess


def find_python_cmd():
    for cmd in ["python3", "python"]:
        if shutil.which(cmd):
            return cmd
    raise RuntimeError("找不到python3或python指令，請確認Python已安裝並加入PATH")


def install():
    repo_root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True
    ).stdout.strip()
    py_cmd = find_python_cmd()
    hook_path = os.path.join(repo_root, ".git", "hooks", "pre-commit")
    content = (
        "#!/bin/sh\n"
        '%s "$(git rev-parse --show-toplevel)/scripts/pre_commit_guard.py"\n'
        "exit $?\n" % py_cmd
    )
    with open(hook_path, "w", newline="\n") as f:
        f.write(content)
    st = os.stat(hook_path)
    os.chmod(hook_path, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    print("✅ pre-commit hook 已安裝於 %s（使用 %s）" % (hook_path, py_cmd))


if __name__ == "__main__":
    install()
