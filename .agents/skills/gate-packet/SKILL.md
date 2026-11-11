# Skill: Gate Packet

## What it teaches
How any agent (usually the Orchestrator) prepares the one document a human
gate decision is made from: complete, honest, and checkable in minutes —
so the human approves facts, not summaries of summaries.

## Steps
1. Header: gate (G1–G6), feature/task IDs, lane, date, who prepared it,
   and the exact decision needed ("approve spec", "apply migration",
   "release to production") — one decision per packet.
2. What changed: the file list (from `git status`/`git diff --stat`, not
   from memory), grouped by owner, with anything outside the task's scope
   explicitly flagged.
3. Summary: what the change does in plain language, mapped to the spec's
   requirement numbers (REQ/BR references), plus what it deliberately
   does NOT do.
4. Test evidence: the **real command output** — the exact commands run
   (`pytest ...`, `./check-contract.sh`, `manage.py check`) with their
   result lines pasted verbatim, including skips and their reasons. A
   claim of "tests pass" without output is an incomplete packet.
5. Review status: Code Reviewer verdict, Security findings (for G5),
   Performance budget status where relevant — each with owner and state.
6. Risks & open items: known limitations, follow-up tasks created,
   anything accepted-but-risky stated plainly (an accepted risk needs the
   human's explicit sign-off at G5/G6).
7. Cost/effort: attempts used per sub-task, anything that exceeded the
   ~400-line task guideline and why.
8. Close with the decision box: approve / request changes / reject —
   and what happens next in each case. Then STOP: no merge, no next
   stage, no "while you decide I'll just…" — the gate is a full stop.

## Example
```markdown
# Gate Packet — G4 (Acceptance) — Feature 001 Booking Lock — Tasks T-011..T-013
Decision needed: accept the booking-lock feature for staging.

Files changed (git diff --stat): 14 files, +612/−38
  apps/bookings/{models,services,api,schemas}.py, migrations/0001 (PROTECTED — reviewed separately)
  apps/scheduling/services.py, apps/bookings/tests/test_booking_race.py ...

Summary: implements REQ-BLK-001..006 (TD-004 lock). Out of scope: payments (PH-05).

Test evidence (verbatim):
  $ pytest apps/bookings apps/scheduling -q        → 21 passed, 0 skipped (PostgreSQL 18)
  $ pytest apps/bookings/tests/test_booking_race.py → 1 passed (two-thread barrier race)
  $ ./check-contract.sh                            → OK, snapshot updated via reviewed diff

Reviews: Code Reviewer — approve (2 nits, fixed). Security — no findings.
Risks: lock TTL fixed at 10 min (config later if gateways prove slower).
Decision: [ ] approve  [ ] request changes  [ ] reject
```

## Common mistakes
- Paraphrased test results ("all green") without the commands and output.
- Hiding skips or known failures in an appendix — they go in the evidence
  section, named, with reasons.
- Bundling two decisions in one packet (spec approval + a migration) —
  the human must be able to say yes to one and no to the other.
- Presenting the packet and continuing work "in parallel" — a gate is a
  stop, not a notification.
- File lists written from memory that miss a config or migration change.
