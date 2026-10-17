---
title: trail deployment status audit
author: Weiwei-alvin
date: 2026-10-17
branch: master
cost: { minutes: 1, tokens: 45849 }
touches:
  - ".harness/decisions/DEC-001.json"
  - ".harness/golden_path.json"
  - ".harness/state.json"
  - harness/runner/storage.py
  - harness/runner/test_review_fixes.py
  - tests/acceptance/README.md
  - tests/acceptance/check.py
  - tests/acceptance/test_checker.py
  - ".codebase-memory/.gitattributes"
  - ".codebase-memory/artifact.json"
---

## Decided
- trail CLI + index (.trail/cache/) are functional: v0.23.0 installed, INDEX.md covers 39 files/527 symbols, `trail check`/`trail map` run clean.
- Full deployment requires both `.trail/` (minus its own gitignored cache/statusline.cjs) AND `.claude/settings.json` to be committed — the SessionStart hook in settings.json is what makes trail load automatically for teammates.

## Tried and ruled out
- Assumed `.trail/` being untracked was the only gap — it isn't. Checked `.gitignore` directly and found line 4 (`.claude/`) blanket-ignores the whole `.claude/` dir, so `.claude/settings.json` (the hook wiring) would never be committed even after `git add .trail/`.

## Watch out
- Before declaring trail "deployed" in this repo, verify with `git ls-files .claude/settings.json` — if empty, the hook isn't tracked regardless of what `.trail/` contains.
- `.gitignore` needs a `.claude/*` + `!.claude/settings.json` style exception (not yet applied — needs user approval per repo's change-control rule in AGENTS.md) to let the hook file through while still ignoring `settings.local.json` and other local state.
- `AGENTS.md` (project instructions describing trail usage) was also untracked at audit time — same commit should include it.
