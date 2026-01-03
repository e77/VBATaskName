"""
Utilities for checking and applying updates on deployed devices.

Remote is the master source of truth (GitHub main). The device should not
accumulate local modifications that block updates.

Update behavior (when applying updates):
- git fetch <remote>
- git reset --hard <remote>/<branch>
- git clean -fd (excluding local runtime/config files)
- docker compose up -d --build
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple


class UpdateError(Exception):
    """Raised when update checks or apply steps fail."""


@dataclass
class UpdateStatus:
    repo_root: Path
    branch: str
    remote: str
    local_revision: str
    remote_revision: str
    ahead: int
    behind: int
    dirty: bool


def _run_command(cmd: List[str], cwd: Path) -> List[str]:
    """
    Run a command, raising UpdateError on failure.
    Returns stdout lines (non-empty).
    """
    result = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        details = stderr or stdout or "unknown error"
        raise UpdateError(f"{' '.join(cmd)} failed: {details}")

    output = (result.stdout or "").strip()
    return [line for line in output.splitlines() if line.strip()]


def _git(args: List[str], cwd: Path) -> List[str]:
    return _run_command(["git", *args], cwd=cwd)


def _locate_repo_root(preferred: Path | None = None) -> Path:
    """Find the git repository root, defaulting to the current working directory."""
    start = preferred or Path(os.getenv("SPOOL_REPO_ROOT", str(Path.cwd())))
    candidates = [start]

    # Fallback to the project root relative to this file for packaged runs.
    candidates.append(Path(__file__).resolve().parent.parent)

    for candidate in candidates:
        try:
            root_line = _git(["rev-parse", "--show-toplevel"], cwd=candidate)[0]
            return Path(root_line).resolve()
        except UpdateError:
            continue

    raise UpdateError("Unable to find a git repository. Set SPOOL_REPO_ROOT to the project root.")


def check_updates(
    remote: str = "origin",
    branch: str | None = None,
    fetch: bool = True,
    repo_root: Path | None = None,
) -> UpdateStatus:
    repo_root = _locate_repo_root(repo_root)

    if fetch:
        _git(["fetch", remote], cwd=repo_root)

    if branch is None:
        branch_line = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root)[0]
        branch = branch_line.strip()

    local_revision = _git(["rev-parse", branch], cwd=repo_root)[0]
    remote_ref = f"{remote}/{branch}"
    remote_revision = _git(["rev-parse", remote_ref], cwd=repo_root)[0]

    ahead_behind = _git(
        ["rev-list", "--left-right", "--count", f"{branch}...{remote_ref}"],
        cwd=repo_root,
    )[0]
    ahead_str, behind_str = ahead_behind.split()

    # IMPORTANT:
    # "dirty" should mean tracked modifications that could matter.
    # Untracked files (.env, logs, dumps, __pycache__) should not trigger this.
    dirty = bool(_git(["status", "--porcelain", "--untracked-files=no"], cwd=repo_root))

    return UpdateStatus(
        repo_root=repo_root,
        branch=branch,
        remote=remote,
        local_revision=local_revision,
        remote_revision=remote_revision,
        ahead=int(ahead_str),
        behind=int(behind_str),
        dirty=dirty,
    )


def apply_updates(status: UpdateStatus) -> Tuple[UpdateStatus, List[str]]:
    """
    Remote is master: force local checkout to match remote branch, then restart Compose stack.

    Returns the refreshed status and a list of log lines for user display.
    """
    logs: List[str] = []

    def log_cmd(cmd: List[str]) -> None:
        logs.append(f"$ {' '.join(cmd)}")

    # 1) Fetch latest from remote
    log_cmd(["git", "fetch", status.remote])
    _git(["fetch", status.remote], cwd=status.repo_root)

    # 2) Hard reset local branch to remote/<branch>
    remote_ref = f"{status.remote}/{status.branch}"
    log_cmd(["git", "reset", "--hard", remote_ref])
    _git(["reset", "--hard", remote_ref], cwd=status.repo_root)

    # 3) Clean untracked files, but keep local runtime/config
    # NOTE: This matches your "appliance" model without nuking .env etc.
    clean_cmd = [
        "git",
        "clean",
        "-fd",
        "-e",
        ".env",
        "-e",
        "backup/dumps",
        "-e",
        "spooltui.log",
        "-e",
        "spooltui/__pycache__",
    ]
    log_cmd(clean_cmd)
    _git(clean_cmd[1:], cwd=status.repo_root)  # pass args only to _git

    # 4) Restart the stack (same as your manual working command)
    log_cmd(["docker", "compose", "up", "-d", "--build"])
    logs.extend(_run_command(["docker", "compose", "up", "-d", "--build"], cwd=status.repo_root))

    refreshed_status = check_updates(
        remote=status.remote,
        branch=status.branch,
        fetch=False,
        repo_root=status.repo_root,
    )
    return refreshed_status, logs
