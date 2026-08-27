#!/usr/bin/env bash
# Auto-commit after any agent file edit. Always-on (no matcher). Fail open. Does not push.
set -u
cat >/dev/null || true

if ! command -v git >/dev/null 2>&1; then
  printf '%s\n' '{}'
  exit 0
fi

root="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  printf '%s\n' '{}'
  exit 0
}
cd "$root" || exit 0

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  printf '%s\n' '{}'
  exit 0
fi

if [[ -d .git/rebase-merge || -d .git/rebase-apply || -f .git/MERGE_HEAD ]]; then
  printf '%s\n' '{}'
  exit 0
fi

git add -A -- . ':!.env' ':!src/config/.env' ':!**/.env' 2>/dev/null || git add -A

# Never stage secrets even if already tracked
git reset -q HEAD -- .env src/config/.env 2>/dev/null || true

if git diff --cached --quiet; then
  printf '%s\n' '{}'
  exit 0
fi

git commit -q -m "chore: auto-commit after file change" >/dev/null 2>&1 || true

# Drop Cursor co-author / Made-with trailers if the agent wrapper appended them.
if git log -1 --format=%B 2>/dev/null | grep -qiE 'cursoragent@cursor\.com|^[[:space:]]*Co-authored-by:[[:space:]]*Cursor|^[[:space:]]*Made-with:[[:space:]]*Cursor'; then
  git log -1 --format=%B \
    | grep -viE 'cursoragent@cursor\.com|^[[:space:]]*Co-authored-by:[[:space:]]*Cursor|^[[:space:]]*Made-with:[[:space:]]*Cursor' \
    | git commit --amend -F - -q >/dev/null 2>&1 || true
fi

printf '%s\n' '{}'
exit 0
