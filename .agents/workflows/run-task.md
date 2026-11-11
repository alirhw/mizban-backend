# Workflow: Run a Task (Orchestrator's operating loop)

Use this when the human gives you (the Orchestrator) a Task ID, e.g. "T-009".
You run the loop; the human decides at gates. Specialists are separate
Antigravity agent conversations, each opened with its definition file from
`.agents/agents/` as its brief.

## 0. Ground yourself
Read, in this order: `AGENTS.md` → `ownership.yaml` → this file → the task
(from the project execution plan and/or `specs/<feature>/tasks.md`) → the
feature's `specs/<feature>/spec.md` and `design.md` if they exist.

## 1. Frame the task
Restate: goal, in-scope, out-of-scope, definition of done, governing
rules (which BR/ARCH/TD apply). If the task text and the repo disagree,
the repo + governing docs win — note the discrepancy in your report.

## 2. Classify the lane
- **Express:** tiny, reversible, no money/auth/schema (copy fix, small
  config). Light review, no full gate packet — still needs reviewer + tests.
- **Standard:** a normal feature task. Full loop below.
- **Full:** touches money (billing/wallets), auth/OTP, migrations in
  bookings/wallets, concurrency, or production settings. Full loop +
  Security Engineer review + explicit human gate before merge.
When in doubt, classify up.

## 3. Spec check
If `specs/<feature>/` lacks a current spec/design/tasks entry for this
task, dispatch in order: Requirements Analyst (spec) → Web Architect
(design, if technical choices are open) → Planner (task breakdown).
Do not dispatch engineers against a missing or stale spec.

## 4. Dispatch
Break the task into sub-tasks, one owner each (see agent files for who
owns what). For each sub-task, open a specialist conversation with:
1. the agent's definition file (`.agents/agents/<agent>.md`) as the brief,
2. the exact sub-task text + the spec/design sections it implements,
3. the relevant `.agents/skills/<skill>/SKILL.md` folders,
4. the instruction: work only on this sub-task, follow
   `.agents/skills/task-execution/SKILL.md`, report with real command output.

**Parallel rule:** sub-tasks in one parallel group must not edit the same
file — check the file lists before dispatching the group. Migrations and
anything in `apps/bookings/services.py` are serial by default.

## 5. Collect and verify
As each specialist reports: check the report's shape (files, commands with
real output, deviations, blockers). Missing test evidence = work not done;
send it back.

## 6. Independent checks (always, both)
- **Code Reviewer** gets the full diff + task text → verdict.
- **Test Engineer** runs/writes the acceptance tests for the task's spec
  criteria (fail-first suite where applicable).
- Full lane adds the **Security Engineer**.
Findings go back to the owning specialist. **Attempt budget: 3 tries per
sub-task.** After the 3rd failure, stop and escalate to the human with the
blocker format (blocker / evidence / affected task / options / decision
required).

## 7. Gate packet and STOP
Assemble the gate packet per `.agents/skills/gate-packet/SKILL.md`
(files from git diff, summary mapped to requirements, verbatim test
output, review verdicts, risks, decision needed) and present it to the
human. Then **stop**. No merging, no next task, no "preparatory work" for
the next stage until the human explicitly approves.

## 8. On approval
Record the decision (the Documentation Engineer updates changelog/docs if
the feature is user-visible), confirm the working tree state is committed
per the human's instruction, and report the task closed — with the final
test evidence attached.

## Standing rules inside the loop
- `ownership.yaml` is binding; a specialist needing another's paths comes
  back to you, never edits across the line.
- Protected paths (bookings/wallets migrations, production settings,
  OpenAPI snapshot) always surface in the gate packet as their own line.
- Nobody approves their own work: not the engineer (reviewer checks), not
  you (the human gates).
