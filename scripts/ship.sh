#!/usr/bin/env bash
# Run from the repo root, on a task/* branch, after reviewing the work.
set -euo pipefail

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

echo "== Commits to publish =="
git log --oneline main..HEAD
read -r -p "Run tests, push and merge into main? (y/N) " answer
[ "$answer" = "y" ] || { echo "Cancelled."; exit 1; }

echo "== Tests =="
QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q -m "not validation and not long"

echo "== Push and pull request =="
git push -u origin "$branch"
gh pr create --fill

echo "== Merge =="
gh pr merge --merge --delete-branch

git checkout main
git pull
git log --oneline -3
