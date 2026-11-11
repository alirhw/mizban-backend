# Design NNN - <feature name>

## 1. Summary
## 2. UX (flows, screens, every state incl. error/empty) - frontend phase link
## 3. API changes (endpoints; same change lands in the OpenAPI snapshot)
## 4. Data model changes (tables, constraints - invariants live in the DB)
## 5. Schemas (Ninja/Pydantic, <Name>CreateIn / <Name>DetailOut)
## 6. Auth (which role may call what; permission checks live server-side)
## 7. Background jobs (Celery: what, when, idempotency)
## 8. External calls (SMS / gateway: timeout, retry, failure behaviour)
## 9. Risks and failure modes (incl. concurrency + threat-model entry)
## 10. Rollout (feature flag name, who gets it first)
## 11. Alternatives considered (and why not)
