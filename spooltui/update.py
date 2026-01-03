"""Utilities for checking and applying updates on deployed devices.

The Raspberry Pi kiosk workflow keeps the git working tree on disk. These
helpers fetch the latest commits, perform a fast-forward pull, and restart the
Compose stack without touching the persistent database volume so existing data
is preserved.
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
    """Run a command and stream its output to avoid blocking pipes."""

    process = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    lines: List[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        cleaned = line.rstrip()
        if cleaned:
            lines.append(cleaned)

    process.wait()

    if process.returncode != 0:
        tail = lines[-20:] if lines else ["(no output)"]
        details = "\n".join(tail)
        raise UpdateError(f"{' '.join(cmd)} failed with code {process.returncode}:\n{details}")

    return lines or ["(no output)"]


def _git(args: List[str], cwd: Path) -> List[str]:
    return _run_command(["git", *args], cwd=cwd)


def _locate_repo_root(preferred: Path | None = None) -> Path:
    """Find the git repository root, defaulting to the current working directory."""

    start = preferred or Path(os.getenv("SPOOL_REPO_ROOT", Path.cwd()))
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
    remote: str = "origin", branch: str | None = None, fetch: bool = True, repo_root: Path | None = None
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

    ahead_behind = _git(["rev-list", "--left-right", "--count", f"{branch}...{remote_ref}"], cwd=repo_root)[0]
    ahead_str, behind_str = ahead_behind.split()

    dirty = bool(_git(["status", "--porcelain"], cwd=repo_root))

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
    """Fast-forward to the remote branch and restart the Compose stack.

    Returns the refreshed status and a list of log lines for user display.
    """

    logs: List[str] = []

    steps = [
        ("git pull", ["git", "pull", "--ff-only", status.remote, status.branch]),
        ("docker compose pull", ["docker", "compose", "pull"]),
        ("docker compose up", ["docker", "compose", "up", "-d", "--build"]),
    ]

    for label, command in steps:
        logs.append(f"$ {' '.join(command)}")
        logs.extend(_run_command(command, cwd=status.repo_root))

    refreshed_status = check_updates(remote=status.remote, branch=status.branch, fetch=False, repo_root=status.repo_root)
    return refreshed_status, logs
