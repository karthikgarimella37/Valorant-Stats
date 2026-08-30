#!/usr/bin/env bash
# Auto-commit after any agent file edit. Always-on (no matcher). Fail open. Does not push.
# Commit subject/body come from staged name-status so history is searchable.
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

# Why: a fixed "auto-commit after file change" subject hides what each edit did.
_commit_message_from_index() {
  local added=0 modified=0 deleted=0 renamed=0 total=0
  local has_feat=0 has_docs=0 has_test=0 has_chore=0
  local names="" body="" status path extra display name

  while IFS=$'\t' read -r status path extra; do
    [[ -z "${status:-}" || -z "${path:-}" ]] && continue
    total=$((total + 1))
    case "$status" in
      A*) added=$((added + 1)); display="A  ${path}" ;;
      D*) deleted=$((deleted + 1)); display="D  ${path}" ;;
      R*) renamed=$((renamed + 1)); display="R  ${path} -> ${extra}" ;;
      M*) modified=$((modified + 1)); display="M  ${path}" ;;
      *) modified=$((modified + 1)); display="${status}  ${path}" ;;
    esac
    if [[ "$total" -le 20 ]]; then
      body="${body}${display}"$'\n'
    fi
    name="${path##*/}"
    if [[ "$total" -le 3 ]]; then
      if [[ -n "$names" ]]; then
        names="${names}, ${name}"
      else
        names="$name"
      fi
    fi
    case "$path" in
      src/*|dagster_orchestration/*) has_feat=1 ;;
      *test*|*tests*) has_test=1 ;;
      *.md|docs/*) has_docs=1 ;;
      .cursor/*|*.json|*.yml|*.yaml|*.toml) has_chore=1 ;;
      *) has_chore=1 ;;
    esac
  done < <(git diff --cached --name-status)

  local type="chore"
  if [[ "$has_feat" -eq 1 ]]; then
    type="feat"
  elif [[ "$has_docs" -eq 1 && "$has_test" -eq 0 && "$has_chore" -eq 0 ]]; then
    type="docs"
  elif [[ "$has_test" -eq 1 && "$has_feat" -eq 0 ]]; then
    type="test"
  fi

  local verb="update"
  if [[ "$added" -gt 0 && "$modified" -eq 0 && "$deleted" -eq 0 && "$renamed" -eq 0 ]]; then
    verb="add"
  elif [[ "$deleted" -gt 0 && "$added" -eq 0 && "$modified" -eq 0 && "$renamed" -eq 0 ]]; then
    verb="remove"
  elif [[ "$renamed" -gt 0 && "$added" -eq 0 && "$modified" -eq 0 && "$deleted" -eq 0 ]]; then
    verb="rename"
  fi

  local subject
  if [[ "$total" -le 3 ]]; then
    subject="${type}: ${verb} ${names}"
  else
    subject="${type}: ${verb} ${total} files"
    [[ "$total" -gt 20 ]] && body="${body}... and $((total - 20)) more"$'\n'
  fi

  printf '%s\n\n%s' "$subject" "$body"
}

msg="$(_commit_message_from_index)"
git commit -q -m "$msg" >/dev/null 2>&1 || true

# Drop Cursor co-author / Made-with trailers if the agent wrapper appended them.
if git log -1 --format=%B 2>/dev/null | grep -qiE 'cursoragent@cursor\.com|^[[:space:]]*Co-authored-by:[[:space:]]*Cursor|^[[:space:]]*Made-with:[[:space:]]*Cursor'; then
  git log -1 --format=%B \
    | grep -viE 'cursoragent@cursor\.com|^[[:space:]]*Co-authored-by:[[:space:]]*Cursor|^[[:space:]]*Made-with:[[:space:]]*Cursor' \
    | git commit --amend -F - -q >/dev/null 2>&1 || true
fi

printf '%s\n' '{}'
exit 0
