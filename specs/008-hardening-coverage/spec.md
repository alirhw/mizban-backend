# Spec 008 — M3 Hardening: Test Coverage (T-029)

**Feature:** 008 — M3 Hardening  
**Task:** T-029 — Line Coverage ≥ 80%  
**Governing Decision:** Decision 8 (2026-11-20)

## 1. Coverage Rule & Configuration
- **Metric:** Line coverage (`branch = false`) **≥ 80% overall**.
- **Source scope:** `apps/` and `core/` only.
- **Excluded:** `*/migrations/*`, `*/tests/*`, `*/test_*.py`, `config/*`.
- **Configuration:** `[tool.coverage.run]` and `[tool.coverage.report]` in `pyproject.toml`; dev dependencies `pytest-cov>=6.0` and `coverage>=7.6` in `requirements.txt`.
- **Command:**
  ```bash
  pytest --cov --cov-report=term-missing -q
  ```

## 2. Baseline vs. Final Coverage (PostgreSQL 16.16)
- **Baseline (`383 passed`):** `3478` statements, `217` missed, **94%** overall line coverage (`apps/accounts`: 92–100%, `apps/billing`: 86–100%, `apps/bookings`: 86–100%, `apps/panoramas`: 88–100%, `apps/reviews`: 100%, `apps/scheduling`: 95–100%, `apps/venues`: 74–100%, `apps/wallets`: 95–100%, `core`: 71–100%).
- **Final (`386 passed`, 0 failed, 0 skipped):** `3478` statements, `192` missed, **94%** overall line coverage (`apps/venues/admin.py`: 74% $\to$ 100%, `core/utils.py`: 79% $\to$ 100%, `core/jalali.py`: 71% $\to$ 80%).
- **Open Item (Real Bug Found, Untouched):** `core/jalali.py:45` and `core/jalali.py:54-55` call `timezone.utc` on `django.utils.timezone` instead of `datetime.timezone.utc`, raising `AttributeError` in `parse_jalali_datetime` and `jalali_slot_window`.
