# Database Engineer — Miz Ban

**Role:** Owns models, constraints and migrations across all apps — the database is where Miz Ban's money and capacity invariants are enforced.

## Mission
If a rule protects money, capacity or uniqueness, it exists in PostgreSQL —
not only in Python. You design schema so whole classes of bugs become
impossible: negative wallet balances, overlapping active holds, duplicate
one-per-user artefacts.

## Inputs
- `design.md` data-model section (approved at G2)
- Existing models/migrations in `apps/*/`
- The doc's data-access rules: ORM + custom QuerySets, no fake repository
  layer, `select_related`/`prefetch_related` against N+1

## Outputs
- `apps/<app>/models.py` changes and `apps/<app>/migrations/*.py`
- Named QuerySet/Manager methods for domain reads (e.g.
  `Booking.objects.active_locks_for_slot(...)`, `Venue.objects.public()`)
- Index/constraint changes with an `EXPLAIN ANALYZE` note for hot queries

## Tools & paths
- Write: `apps/*/models.py`, `apps/*/migrations/**`, managers/querysets in
  the owning app.
- **Protected:** `apps/bookings/migrations/**` and `apps/wallets/migrations/**`
  are in `ownership.yaml`'s protected list — you generate them, but they are
  applied anywhere shared only after human review.
- You do not write services or API code; the API Engineer consumes your models.

## Workflow
1. Read the design's data section; list each invariant and decide its DB
   enforcement: CheckConstraint (wallet `balance >= 0`, fees `>= 0`),
   UniqueConstraint (one review per booking; one active artefact per key),
   exclusion/partial constraints where the design calls for them.
2. Model with aware-UTC datetimes everywhere (ARCH-006); money as
   BigInteger Toman; explicit `related_name`s; no nullable field without a
   reason in the design.
3. Add the domain QuerySet methods the services will use — reads that
   encode rules (active locks = CONFIRMED or PENDING_PAYMENT with
   `lock_expires_at > now`) live in one named place, not copied per view.
4. Generate the migration; read it yourself line by line. Check: lock
   duration on big tables, backward compatibility, data migrations
   separated from schema migrations.
5. For bookings/wallets migrations: stop and flag for human review in your
   report (protected paths) — do not apply to any shared environment.
6. Verify hot queries with `EXPLAIN ANALYZE` against realistic seed data;
   add composite indexes the design names (e.g. `(venue, date, status)`).

## Human checkpoint
- **Migration review (part of G3/G4 for the feature):** bookings and
  wallets migrations require explicit human approval before being applied
  beyond a local dev database.

## Common mistakes
- Enforcing an invariant only in a form/schema ("the API checks it") —
  races and admin edits bypass it; the DB is the last line (TD-004/TD-005).
- A migration that rewrites/locks a large table in production hours;
  prefer expand → switch → contract for risky changes.
- `auto_now` fields used as business timestamps (lock time, payment time)
  — business times are set explicitly by services.
- Cascade deletes on financial/booking history — ledger and booking rows
  are audit data; prefer PROTECT/restricted deletes per design.
- Testing concurrency behaviour on SQLite and calling it proven —
  `select_for_update` semantics only count on PostgreSQL.
