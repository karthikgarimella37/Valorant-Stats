---
name: session-continuity
description: >-
  Maintain session-agnostic project context in PROJECT_STATUS.md (aim, current
  focus, done, next up, blockers). Use at the start of every chat in this repo,
  after meaningful progress, when switching tasks, before ending a session, or
  when the user mentions status, progress, context, handoff, or continuing work.
---

# Session Continuity

Keep durable project context in `PROJECT_STATUS.md` at the repo root so every Cursor chat can continue without prior conversation history.

## When to apply

1. **Session start** — before planning or coding, read `PROJECT_STATUS.md`
2. **After meaningful progress** — update the file when work completes or focus changes
3. **Task switch / end of session** — refresh Current focus, Done, Next up, Session log
4. **User asks** about status, progress, what's next, or handoff

## Session-start protocol

1. Read `PROJECT_STATUS.md` (create it from the template below if missing)
2. Read `ENGINEERING_STANDARDS.md` (simple English, concise chat, coding rules)
3. Treat **Aim**, **Current focus**, **Done**, and **Next up** as ground truth
4. In your first reply for a new chat, briefly acknowledge aim + current focus (1–2 short sentences) before diving into the user's request unless they ask something unrelated
5. Prefer continuing **Current focus** / **Next up** unless the user redirects
6. All generated code must follow `ENGINEERING_STANDARDS.md` and the `engineering-standards` skill

## Update protocol

Edit `PROJECT_STATUS.md` in place. Do not invent a parallel status file.

1. Set **Last updated** to today's date and a short **Updated by** note (task or chat topic)
2. Keep **Aim** stable unless the user explicitly changes project goals
3. Rewrite **Current focus** to the single active thread of work
4. Move finished items from **Next up** → **Done** (checkboxes)
5. Refresh **Status** table if area state changed
6. Add/clarify **Open questions / blockers** when stuck or undecided
7. Append one row to **Session log** (date + 1-line summary of what changed)
8. Keep the file concise: prune Session log to the last ~15 rows if it grows long
9. Never put secrets, API keys, tokens, or credentials in this file

## File template

If `PROJECT_STATUS.md` is missing, create it at the repo root:

```markdown
# Project Status

> Session-agnostic source of truth. Commit and push after meaningful updates.

**Last updated:** YYYY-MM-DD
**Updated by:** <short note>

---

## Aim

<1–3 sentences: what we are building and why>

## Current focus

- <what this session / the next session should work on>

## Status

| Area | State | Notes |
|------|--------|-------|
| Overall | Not started | |

## Done

- [x] <completed work>

## Next up

- [ ] <ordered upcoming work>

## Open questions / blockers

- <none, or concrete blockers>

## Session log

| Date | Session summary |
|------|-----------------|
| YYYY-MM-DD | <one line> |
```

## End-of-session checklist

Before the user stops (or when they say wrap up / handoff / update status):

- [ ] `PROJECT_STATUS.md` reflects reality
- [ ] Current focus is accurate for the *next* session
- [ ] Next up is ordered and actionable
- [ ] Remind the user to **commit and push** `PROJECT_STATUS.md` (and `.cursor/` if changed) so other sessions pick it up — do not commit unless they ask

## Anti-patterns

- Do not rely on chat history as the source of truth
- Do not duplicate long design docs here — link to files instead
- Do not leave Current focus stale after finishing a task
- Do not overwrite Aim with session noise
