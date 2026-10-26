#!/usr/bin/env bash
# Publish a task branch: the full suite, push, pull request, merge on GitHub, then main fast-forwarded.
# Run by the owner only, on a task/* branch, after reviewing the work; from the main checkout or from a worktree.
#
#   scripts/ship.sh [--dry-run]
#
# It never checks out main in a worktree: the pull request is merged on GitHub (gh pr merge), the remote branch is
# deleted, and main is fast-forwarded to origin/main where it is checked out (another worktree, which must be
# clean) or, when no worktree has it, as a ref only. From the main checkout (not a linked worktree, main checked out
# nowhere) it then checks out main and deletes the local task branch, as it always did. From a linked worktree the
# task branch stays checked out there (CONTRIBUTING.md, "Worktrees").
#
# --dry-run checks the branch and the tree, then prints every command it would run (the suite included) and runs
# none of them.
set -euo pipefail

DRY_RUN=0
case "${1:-}" in
  --dry-run) DRY_RUN=1 ;;
  "") ;;
  *) echo "Usage: scripts/ship.sh [--dry-run]"; exit 64 ;;
esac

cd "$(git rev-parse --show-toplevel)"

run() {
  if [ "$DRY_RUN" = 1 ]; then
    echo "[dry-run] $*"
  else
    "$@"
  fi
}

branch=$(git branch --show-current)
case "$branch" in
  task/*) ;;
  *) echo "Not on a task/* branch (on '$branch'). Aborting."; exit 1 ;;
esac

if [ -n "$(git status --porcelain)" ]; then
  echo "Working tree not clean. Commit or discard changes first:"
  git status --short
  exit 1
fi

# The worktree that has main checked out, if any (this one never has: it is on the task branch).
main_tree=$(git worktree list --porcelain | awk '/^worktree /{t=substr($0, 10)} /^branch refs\/heads\/main$/{print t}')
linked=0
[ "$(git rev-parse --path-format=absolute --git-dir)" != "$(git rev-parse --path-format=absolute --git-common-dir)" ] && linked=1

if [ -n "$main_tree" ] && [ -n "$(git -C "$main_tree" status --porcelain)" ]; then
  echo "main is checked out in $main_tree and that tree is not clean; it could not be fast-forwarded. Aborting."
  exit 1
fi

echo "== Commits to publish =="
git log --oneline main..HEAD
if [ -n "$main_tree" ]; then
  echo "main is checked out in $main_tree: it is fast-forwarded there after the merge."
elif [ "$linked" = 1 ]; then
  echo "main is checked out nowhere: its ref is fast-forwarded after the merge."
fi
if [ "$DRY_RUN" = 0 ]; then
  read -r -p "Run tests, push and merge into main? (y/N) " answer
  [ "$answer" = "y" ] || { echo "Cancelled."; exit 1; }
fi

echo "== Tests =="
if [ "$DRY_RUN" = 1 ]; then
  echo "[dry-run] QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q -m \"not validation and not long and not bench\""
else
  QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q -m "not validation and not long and not bench"
fi

echo "== Push and pull request =="
run git push -u origin "$branch"
run gh pr create --fill

echo "== Merge on GitHub =="
run gh pr merge "$branch" --merge
run git push origin --delete "$branch"

echo "== main =="
run git fetch origin
if [ -n "$main_tree" ]; then
  run git -C "$main_tree" merge --ff-only origin/main
  run git -C "$main_tree" log --oneline -3
elif [ "$linked" = 1 ]; then
  run git fetch origin main:main
  run git log --oneline -3 main
else
  run git fetch origin main:main
  run git checkout main
  run git branch -d "$branch"
  run git log --oneline -3
fi
