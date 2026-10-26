"""scripts/ship.sh --dry-run on throw-away repositories (D-180): from a worktree it never checks out main and
fast-forwards main where it is checked out; from the main checkout it ends on main as before; it refuses a dirty tree,
a dirty main worktree and a branch that is not task/*. Nothing is pushed: the dry run prints the commands only."""

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "ship.sh"


def _git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=env).stdout


def _repos(tmp_path: Path) -> tuple[Path, Path]:
    """A primary checkout on main and a linked worktree on task/x with one commit."""
    main = tmp_path / "repo"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    (main / "a.txt").write_text("a\n")
    _git(main, "add", "a.txt")
    _git(main, "commit", "-q", "-m", "first")
    tree = tmp_path / "repo-task"
    _git(main, "worktree", "add", "-q", "-b", "task/x", str(tree))
    (tree / "b.txt").write_text("b\n")
    _git(tree, "add", "b.txt")
    _git(tree, "commit", "-q", "-m", "Task x: b")
    return main, tree


def _ship(cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(SCRIPT), "--dry-run"], cwd=cwd, capture_output=True, text=True, timeout=60)


def test_the_script_parses() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_from_a_worktree_main_is_fast_forwarded_where_it_is_checked_out(tmp_path: Path) -> None:
    main, tree = _repos(tmp_path)
    result = _ship(tree)
    assert result.returncode == 0, result.stdout + result.stderr
    out = result.stdout
    assert "Task x: b" in out
    assert '[dry-run] QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q -m "not validation and not long and not bench"' in out
    assert "[dry-run] git push -u origin task/x" in out
    assert "[dry-run] gh pr merge task/x --merge" in out and "--delete-branch" not in out
    assert "[dry-run] git push origin --delete task/x" in out
    assert f"[dry-run] git -C {main} merge --ff-only origin/main" in out
    assert "git checkout main" not in out and "git branch -d" not in out
    assert _git(tree, "branch", "--show-current").strip() == "task/x"  # nothing ran


def test_from_a_worktree_with_main_checked_out_nowhere_only_the_ref_moves(tmp_path: Path) -> None:
    main, tree = _repos(tmp_path)
    _git(main, "checkout", "-q", "--detach")
    out = _ship(tree).stdout
    assert "[dry-run] git fetch origin main:main" in out and "git checkout main" not in out


def test_from_the_main_checkout_it_ends_on_main(tmp_path: Path) -> None:
    main, tree = _repos(tmp_path)
    _git(main, "worktree", "remove", str(tree))
    _git(main, "checkout", "-q", "task/x")
    result = _ship(main)
    assert result.returncode == 0, result.stdout + result.stderr
    out = result.stdout
    assert "[dry-run] git fetch origin main:main" in out
    assert "[dry-run] git checkout main" in out and "[dry-run] git branch -d task/x" in out


def test_refusals(tmp_path: Path) -> None:
    main, tree = _repos(tmp_path)
    (main / "a.txt").write_text("changed\n")
    result = _ship(tree)
    assert result.returncode == 1 and "is not clean" in result.stdout
    _git(main, "checkout", "-q", "a.txt")
    (tree / "c.txt").write_text("c\n")
    result = _ship(tree)
    assert result.returncode == 1 and "Working tree not clean" in result.stdout
    result = _ship(main)
    assert result.returncode == 1 and "Not on a task/* branch" in result.stdout
