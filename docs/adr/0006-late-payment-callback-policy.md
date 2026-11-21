# ADR-006: Late Payment Callback Policy and Atomic Slot Re-Check (ARCH-ISSUE-02)

- **Status:** Accepted (Product Owner Decision 2026-11-20)
- **Date:** 2026-11-21
- **Author:** Web Architect & Orchestrator
- **Approved by:** Product Owner (Gate T-021 Decision)
- **Task:** T-021 — Implement Payment Callback and Booking Confirmation Endpoint
- **References:** ADR-004 (Internal Wallet & Double-Entry Ledger), ARCH-005 (Payment Gateway & Double-Entry Ledger), TD-004 (Concurrency Lock & State Machine), BR-003, BR-004

---

## 1. Context and Problem Statement

When a customer initiates a reservation on Miz Ban, a temporary database lock is held for 10 minutes (`lock_expires_at = now + 10m`, TD-004) while the customer completes online payment at the Iranian Payment Gateway (IPG).

Due to bank network latency, Shaparak card verification delays, or user deliberation, the payment gateway callback may arrive at the Miz Ban callback endpoint after the 10-minute lock has elapsed (`now > lock_expires_at`). During this elapsed period:
1. The original booking record is either still in `PENDING_PAYMENT` (with `lock_expires_at <= now`), or has been lazily updated to `EXPIRED` by another client's availability query (`is_table_slot_occupied`).
2. The table slot may either remain completely unreserved (free), or may have been locked/confirmed by another customer.

If the gateway reports that the customer's payment was successfully debited (`SUCCESS` with exact amount match), how should Miz Ban process this late callback?

---

## 2. Decision: Atomic Slot Re-Check & Bank Card Refund Policy

The Product Owner formally approved the following policy on 2026-11-20 (Decision 2):

### Decision Tree at Callback Verification:
1. **Server-Side Verification First (Outside Transaction):**
   - The gateway verification request (`verify_payment_transaction`) is executed server-to-server.
   - If verification fails or times out, the transaction status transitions to `FAILED` or `TIMEOUT`, and the booking remains unconfirmed (lock lapses).
2. **Atomic Slot Re-Check (Inside `transaction.atomic()` with `select_for_update()`):**
   - If verification succeeds with the exact reservation fee:
     * Acquire an exclusive row lock on the `TablePin` (`TablePin.objects.select_for_update().get(...)`), matching the lock discipline in `create_booking_lock`.
     * Re-fetch the target `Booking` under `select_for_update()`.
     * Check active occupancy on that table pin for the target slot (`slot_date`, `slot_start_time`), **excluding this booking itself**.
3. **Outcomes:**
   - **Case A (On-Time Success):**
     * Booking is `PENDING_PAYMENT` and lock has not expired (`lock_expires_at > now`).
     * Transition booking: `PENDING_PAYMENT` $\to$ `CONFIRMED`.
     * `PaymentTransaction.refund_required = False`.
   - **Case B (Late Callback — Slot Still Free):**
     * Lock has expired (`lock_expires_at <= now` or booking status is `EXPIRED`), but the slot is **still free** (no other confirmed or active hold booking exists).
     * The booking is confirmed: transition `PENDING_PAYMENT` $\to$ `CONFIRMED` or guarded transition `EXPIRED` $\to$ `CONFIRMED`.
     * `PaymentTransaction.refund_required = False`.
   - **Case C (Late Callback — Slot Taken by Another Booking):**
     * The slot has been claimed by another booking (`CONFIRMED` or active `PENDING_PAYMENT`).
     * **Under no circumstances may Miz Ban double-book a table.**
     * Do **NOT** confirm the late booking; the booking remains or becomes `EXPIRED`.
     * The payment transaction status remains `SUCCESS` (the customer's bank account was debited), but is flagged with:
       ```python
       tx.refund_required = True
       ```
   - **Case D (Cancelled Booking):**
     * If the customer previously cancelled the booking (`BookingStatus.CANCELLED`), the booking is **never resurrected**. It remains `CANCELLED` and `tx.refund_required = True`.

---

## 3. Bank Card Refund vs. Wallet Balance Policy

- **Mandatory Bank Card Refund for Booking Conflicts (Case C & D):**
  - When payment succeeds but the booking cannot be honored due to lock expiration and slot conflict, the refund **must return to the customer's original bank card/account**.
  - **The refund must NEVER be credited to the in-app wallet.**
  - **Rationale:** Under BR-004 and TD-005, the in-app wallet is closed-loop and non-withdrawable to bank cards; it is reserved strictly for voluntary customer cancellations initiated at least 36 hours before slot start time. Forcing a customer into store credit when the system failed to secure their reservation due to a timeout conflict violates consumer trust and Iranian e-commerce payment regulations.
- **Sandbox Phase Scope:**
  - In this Sandbox/MVP phase, real bank refund APIs are not yet integrated.
  - The system records `refund_required = True` on the `PaymentTransaction` row, creating an auditable ledger entry for administrative reconciliation or automated gateway refund dispatch in subsequent phases.

---

## 4. State Machine Invariant Addition

To support Case B (late payment when the slot was lazily marked `EXPIRED`), the `Booking` state machine is extended with exactly one guarded transition:
```python
VALID_TRANSITIONS = {
    ...
    BookingStatus.EXPIRED: {
        BookingStatus.CONFIRMED,  # Guarded transition for late payment confirmation when slot is free (ADR-006)
    },
    ...
}
```
This transition is permitted **only** within the payment callback confirmation service when verified by a `SUCCESS` transaction and a verified free slot.
