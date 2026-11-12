# Design 003 — Slot Generation Engine
Feature: 003 Slot Generation Engine | Status: Approved

## 1. Domain Modeling
* `Slot`: Immutable dataclass representing a generated slot:
  * `start: datetime`: Aware UTC instant when the slot begins.
  * `end: datetime`: Aware UTC instant when the 90-minute slot ends (`start + 90m`).
  * `is_bookable: bool`: `True` if `start - now >= 24h` (BR-002), `False` otherwise.
  * `disabled_reason: Optional[str]`: `None` if bookable; `"LEAD_TIME_VIOLATION"` if <24h away.

## 2. Operating Window Construction
* Venue operating hours give `open_time` and `close_time` (wall clock in `Asia/Tehran`).
* For date `D`:
  * `open_local = datetime.combine(D, open_time, tzinfo=ZoneInfo("Asia/Tehran"))`
  * If `close_time <= open_time`:
    * `close_local = datetime.combine(D + timedelta(days=1), close_time, tzinfo=ZoneInfo("Asia/Tehran"))`
  * Else:
    * `close_local = datetime.combine(D, close_time, tzinfo=ZoneInfo("Asia/Tehran"))`
* Both are converted to aware UTC:
  * `open_utc = open_local.astimezone(timezone.utc)`
  * `close_utc = close_local.astimezone(timezone.utc)`

## 3. Slot Iteration
* `SLOT_DURATION = timedelta(minutes=90)`
* `CYCLE_STEP = timedelta(minutes=120)` (90m slot + 30m buffer)
* `LEAD_THRESHOLD = timedelta(hours=24)`
* Loop:
  ```python
  curr = open_utc
  while curr + SLOT_DURATION <= close_utc:
      is_bookable = (curr - now) >= LEAD_THRESHOLD
      yield Slot(
          start=curr,
          end=curr + SLOT_DURATION,
          is_bookable=is_bookable,
          disabled_reason=None if is_bookable else "LEAD_TIME_VIOLATION",
      )
      curr += CYCLE_STEP
  ```

## 4. Venue Integration & Weekday Mapping
* Python `date.weekday()` returns `0=Monday..6=Sunday`.
* Matches `OperatingHours.Weekday` integer values (0 to 6).
* Query `venue.operating_hours.filter(weekday=target_date.weekday()).first()`.
* If not found -> venue is closed on that day -> return `[]`.
* If found -> pass `open_time` and `close_time` to `generate_slots`.

## 5. API Exposure
* `GET /api/v1/scheduling/venues/{venue_id}/slots?date=YYYY-MM-DD` (or Jalali date string `1404/10/15`).
* Returns `List[SlotOut]` with Jalali formatted timestamps for presentation.
* Never caches availability response (ARCH-004).
