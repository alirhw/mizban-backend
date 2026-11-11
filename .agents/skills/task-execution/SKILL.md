# Skill: Task Execution (repo rules)

## What it teaches
The standing orders every agent in this repo works under, taken from the
project's execution plan (Chat-05 rules) and `AGENTS.md`: one task, exact
scope, framework-native first, proven with real output.

## Steps
1. **One task only.** Execute exactly the Task ID you were given. Never
   silently implement blocked, downstream or "while I'm here" tasks.
2. **Inspect before writing.** Read the repo state (files, existing
   patterns, current tests) before deciding paths. Paths in a brief are
   proposals; the repo is the truth. Record deviations, don't guess.
3. **Read the governing docs.** `AGENTS.md` always; the ADR/TD sections
   named by your task (e.g. TD-004 before touching booking locks). If a
   governing document is unavailable, that is an IMPLEMENTATION BLOCKER —
   report it, don't invent its contents.
4. **Stay inside ownership.** Write only in your `ownership.yaml` paths.
   Need a file outside them? Stop and route through the Orchestrator.
5. **Framework-native first.** Exhaust Django / Django Ninja / stdlib
   capabilities before adding a dependency; a new dependency needs the
   doc's dependency-policy answers documented in your report.
6. **Business logic in services**, transactions per ARCH-002, errors via
   `core.exceptions` envelope, times in UTC, money in integer Toman.
7. **Test as you go.** Add the narrowest useful tests for behaviour you
   change, plus integration tests at boundaries (API, DB constraints,
   callbacks). Run them and keep the real output.
8. **No silent scope change.** If the task as written conflicts with the
   architecture or a business rule, stop that part and report — do not
   "fix" the architecture on your own authority.
9. **Report in the fixed shape:** what was done (files), commands run with
   real output, tests added/results, deviations from the brief and why,
   blockers (if any) in the blocker format below.
10. **Blocker format** (when stuck): blocker — evidence — affected task —
    options — decision required (from the human/Orchestrator). Then stop
    that task; other independent work may continue only if the
    Orchestrator says so.

## Example
```markdown
# Report — T-009 (venue owner workflows)
Done: owner CRUD endpoints + approval actions in Django Admin; cache
invalidation for venue metadata on edit (1h TTL key venue:metadata:{id}).
Files: apps/venues/{api,services,schemas,admin}.py, apps/venues/tests/test_owner_api.py
Commands (real output):
  $ pytest apps/venues -q   → 19 passed
  $ python manage.py check  → no issues
Deviations: none.
Blockers: none.
Notes: approval still requires staff permission check in service layer —
test test_owner_cannot_approve_own_venue covers the negative case.
```

## Common mistakes
- Doing the next task because "it was almost done anyway" (breaks gates,
  ownership and review — the plan's order is a decision, not a hint).
- Claiming "tests pass" from memory or from a partial run — paste output.
- Inventing a missing requirement/ADR instead of declaring a blocker.
- Adding a package for a five-line helper (dependency policy violation).
- Quietly widening a schema or endpoint beyond the task "for future use".
