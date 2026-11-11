# Spec NNN - <feature name>
Status: Draft | Owner: <human> | Lane: Express | Standard | Full
<!-- Miz Ban hint: any feature touching bookings, payments or the wallet is
     Lane FULL - no exceptions. Cite the BR-xxx rules it implements. -->

## 1. Problem and goal (3-5 lines, no solution)

## 2. User stories
US-01  As a <customer | venue owner | admin>, I want <capability>, so that <benefit>.

## 3. Requirements (numbered, EARS style)
REQ-XXX-001  When <trigger>, the system shall <response>.
REQ-XXX-002  If <unwanted event>, then the system shall <response + error_code>.

## 4. Business rules touched
BR-00x - <what this feature must respect, e.g. BR-001 90-minute slot + 30-minute buffer>

## 5. Non-functional targets
Performance / security / accessibility numbers (tested against exactly these).

## 6. Acceptance criteria (Gherkin)
Scenario: <name>
  Given <real starting state, with real numbers>
  When <action>
  Then <observable outcome, incl. the error envelope on failure paths>

## 7. Out of scope (explicit)
## 8. Open questions (each gets a business answer, or "not in v1")
