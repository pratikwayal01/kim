"""
Heapq-based single-thread scheduler for kim.
"""

import datetime
import heapq
import re
import threading
import time
from copy import deepcopy
from typing import Callable, Dict, List, Optional

from .core import log


# ── Internal event object stored in the heap ──────────────────────────────────


class _Event:
    """
    A single scheduled fire event.

    Stored in a min-heap ordered by `fire_at` (Unix timestamp).
    Cancelled events are left in the heap but skipped when popped —
    this avoids the O(n) cost of finding and removing them mid-heap.
    """

    __slots__ = ("fire_at", "reminder", "cancelled")

    def __init__(self, fire_at: float, reminder: dict):
        self.fire_at = fire_at
        self.reminder = reminder
        self.cancelled = False

    # Heap comparison — only care about fire time
    def __lt__(self, other: "_Event") -> bool:
        return self.fire_at < other.fire_at

    def __le__(self, other: "_Event") -> bool:
        return self.fire_at <= other.fire_at


# ── Public scheduler ──────────────────────────────────────────────────────────


class KimScheduler:
    """
    Single-thread heapq scheduler that replaces KIM's per-reminder threads.

    The heap always contains the *next* fire event for each reminder.
    The scheduler thread sleeps until the earliest event, fires it, then
    immediately re-schedules that reminder at +interval and goes back to sleep.

    Adding / removing / updating reminders wakes the scheduler via a
    threading.Event so the sleep is interrupted and the heap is re-evaluated.
    """

    # How long (seconds) the scheduler will sleep when the heap is empty.
    # It will wake up sooner if a new reminder is added.
    _IDLE_SLEEP = 60.0
    # Max time to sleep when checking for one-shots (shorter to reduce drift)
    _ONESHOT_CHECK_SLEEP = 1.0

    def __init__(
        self,
        config: dict,
        notifier: Callable[[dict], None],
    ):
        """
        Parameters
        ----------
        config:
            Parsed ~/.kim/config.json dict (same schema KIM already uses).
        notifier:
            Callable that receives a reminder dict and sends the notification.
            This is called from the scheduler thread — keep it fast or hand
            off to a separate thread if the notification can block.
        """
        self._notifier = notifier
        self._lock = threading.Lock()
        self._wakeup = threading.Event()  # set to interrupt sleep
        self._stop_flag = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # name → live _Event (the one currently in the heap, not cancelled)
        self._live: Dict[str, _Event] = {}

        # min-heap of _Event objects
        self._heap: List[_Event] = []

        self._load_config(config)

    # ── Config loading ─────────────────────────────────────────────────────

    def _load_config(self, config: dict) -> None:
        """Parse config and populate the heap. Called once at init."""
        now = time.time()
        for reminder in config.get("reminders", []):
            if not reminder.get("enabled", True):
                continue

            if reminder.get("at"):
                fire_at = self._next_at_fire(reminder)
                if fire_at is None:
                    log.warning(
                        "Skipping reminder %r — invalid 'at' value",
                        reminder.get("name"),
                    )
                    continue
            else:
                interval = self._parse_interval(reminder)
                if interval is None:
                    log.warning(
                        "Skipping reminder %r — invalid interval", reminder.get("name")
                    )
                    continue
                fire_at = now + interval

            event = _Event(fire_at=fire_at, reminder=deepcopy(reminder))
            self._live[reminder["name"]] = event
            heapq.heappush(self._heap, event)

    @staticmethod
    def _next_at_fire(reminder: dict) -> Optional[float]:
        """
        For reminders with an 'at' field (HH:MM daily schedule), compute the
        Unix timestamp of the next occurrence.

        'at' field is "HH:MM" (24h).
        Optional 'timezone' field is an IANA tz name; defaults to local time.
        Returns None if the 'at' value is invalid.
        """
        at_str = reminder.get("at")
        if not at_str:
            return None
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", at_str.strip())
        if not m:
            log.warning(
                "Invalid 'at' value for reminder %r: %r", reminder.get("name"), at_str
            )
            return None
        hour, minute = int(m.group(1)), int(m.group(2))

        tz_name = reminder.get("timezone")
        try:
            if tz_name:
                from .core import _get_utc_offset

                tz = _get_utc_offset(tz_name)
            else:
                tz = datetime.datetime.now().astimezone().tzinfo
        except Exception as e:
            log.warning(
                "Could not resolve timezone %r for reminder %r: %s",
                tz_name,
                reminder.get("name"),
                e,
            )
            tz = datetime.datetime.now().astimezone().tzinfo

        now = datetime.datetime.now(tz=tz)
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += datetime.timedelta(days=1)
        return candidate.timestamp()

    @staticmethod
    def _parse_interval(reminder: dict) -> Optional[float]:
        """
        Convert interval (or interval_minutes for backward compat) to seconds.
        Supports:
          - int / float  → treated as minutes
          - "30m"        → 30 minutes
          - "2h"         → 2 hours
          - "1d"         → 1 day
        Returns None if the value is invalid, zero, or negative.
        """
        raw = reminder.get("interval") or reminder.get("interval_minutes", 0)
        try:
            if isinstance(raw, (int, float)):
                if raw <= 0:
                    return None
                return float(raw) * 60
            raw = str(raw).strip().lower()
            if not raw:
                return None
            if raw.endswith("d"):
                val = float(raw[:-1])
                return val * 86400 if val > 0 else None
            if raw.endswith("h"):
                val = float(raw[:-1])
                return val * 3600 if val > 0 else None
            if raw.endswith("m"):
                val = float(raw[:-1])
                return val * 60 if val > 0 else None
            val = float(raw)
            return val * 60 if val > 0 else None
        except (ValueError, TypeError):
            return None

    # ── Public API (thread-safe) ───────────────────────────────────────────

    def start(self) -> None:
        """Start the background scheduler thread."""
        if self._thread and self._thread.is_alive():
            raise RuntimeError("KimScheduler is already running")
        self._stop_flag.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="kim-scheduler",
            daemon=True,
        )
        self._thread.start()
        log.info("KimScheduler started (%d reminders)", len(self._live))

    def stop(self) -> None:
        """Signal the scheduler to stop and wait for it to exit."""
        self._stop_flag.set()
        self._wakeup.set()  # interrupt any active sleep
        if self._thread:
            self._thread.join(timeout=5)
        log.info("KimScheduler stopped")

    def add_reminder(self, reminder: dict) -> None:
        """
        Add a new reminder at runtime (kim add).
        If a reminder with the same name already exists it is replaced.
        """
        name = reminder["name"]

        if reminder.get("at"):
            fire_at = self._next_at_fire(reminder)
            if fire_at is None:
                raise ValueError(f"Invalid 'at' value for reminder {name!r}")
        else:
            interval = self._parse_interval(reminder)
            if interval is None:
                raise ValueError(f"Invalid interval for reminder {name!r}")
            fire_at = time.time() + interval

        with self._lock:
            # Cancel any existing event for this name
            if name in self._live:
                self._live[name].cancelled = True

            event = _Event(
                fire_at=fire_at,
                reminder=deepcopy(reminder),
            )
            self._live[name] = event
            heapq.heappush(self._heap, event)

        self._wakeup.set()  # wake scheduler to re-evaluate next fire time
        log.info("Added reminder %r (fire_at=%s)", name, time.ctime(fire_at))

    def remove_reminder(self, name: str) -> bool:
        """
        Remove a reminder by name (kim remove).
        Returns True if the reminder existed, False otherwise.
        """
        with self._lock:
            event = self._live.pop(name, None)
            if event is None:
                return False
            event.cancelled = True

        self._wakeup.set()
        log.info("Removed reminder %r", name)
        return True

    def _oneshot_add(self, reminder: dict) -> None:
        """
        Add a one-shot reminder that fires at a specific time and does not reschedule.
        Internal method called by daemon for persisted one-shot reminders.
        """
        name = reminder["name"]
        fire_at = reminder.get("_oneshot_fire_at")
        if fire_at is None:
            log.warning("One-shot reminder missing fire_at: %r", name)
            return

        with self._lock:
            # Cancel any existing event for this name
            if name in self._live:
                self._live[name].cancelled = True

            event = _Event(
                fire_at=fire_at,
                reminder=deepcopy(reminder),
            )
            self._live[name] = event
            heapq.heappush(self._heap, event)

        self._wakeup.set()
        log.info("Added one-shot reminder %r (fires at %s)", name, time.ctime(fire_at))

    def list_reminders(self) -> List[dict]:
        """Return a snapshot of all active reminders (kim list)."""
        with self._lock:
            return [deepcopy(e.reminder) for e in self._live.values()]

    def status(self) -> List[dict]:
        """
        Return status of all reminders including next fire time (kim status).
        """
        now = time.time()
        with self._lock:
            return [
                {
                    "name": e.reminder["name"],
                    "title": e.reminder.get("title", ""),
                    "next_in": max(0.0, e.fire_at - now),
                    "enabled": e.reminder.get("enabled", True),
                }
                for e in self._live.values()
            ]

    # ── Scheduler loop ─────────────────────────────────────────────────────

    def _run(self) -> None:
        """Main loop — runs in the background scheduler thread."""
        while not self._stop_flag.is_set():
            try:
                with self._lock:
                    # Clear wakeup inside the lock so any wakeup signal set after
                    # we read the heap but before we sleep is not lost.
                    self._wakeup.clear()
                    # Drain cancelled events from the top of the heap
                    while self._heap and self._heap[0].cancelled:
                        heapq.heappop(self._heap)
                    next_fire = self._heap[0].fire_at if self._heap else None
                    # Check for one-shots while holding the lock so we read
                    # live cancelled flags, not a stale snapshot.
                    has_oneshot = any(
                        "_oneshot_fire_at" in e.reminder
                        for e in self._heap
                        if not e.cancelled
                    )

                if next_fire is None:
                    sleep_for = self._IDLE_SLEEP
                else:
                    time_until_next = max(0.0, next_fire - time.time())
                    if has_oneshot:
                        sleep_for = min(time_until_next, self._ONESHOT_CHECK_SLEEP)
                    else:
                        sleep_for = time_until_next

                # Sleep until next event (or woken early by add/remove/stop)
                self._wakeup.wait(timeout=sleep_for)

                if self._stop_flag.is_set():
                    break

                # Fire all events that are due (handles clock drift / burst)
                self._fire_due_events()
            except Exception:
                log.exception("Unexpected error in scheduler loop")
                # Continue loop after logging; if it's a serious error,
                # the loop may repeat. Consider stopping after repeated errors.
                # For now, just sleep a bit to avoid tight loop.
                time.sleep(1)

    def _fire_due_events(self) -> None:
        """Pop and fire every event whose fire_at <= now, then re-schedule."""
        now = time.time()
        to_reschedule = []

        with self._lock:
            while self._heap and self._heap[0].fire_at <= now:
                event = heapq.heappop(self._heap)
                if event.cancelled:
                    continue
                # Is this still the live event for this name?
                name = event.reminder["name"]
                if self._live.get(name) is not event:
                    continue  # superseded by add/update
                to_reschedule.append(event)

        # Fire outside the lock so notifier can call add/remove safely
        for event in to_reschedule:
            # Check if this is a one-shot reminder (has _oneshot_fire_at)
            is_oneshot = "_oneshot_fire_at" in event.reminder

            try:
                # Run notifier in a daemon thread so a slow/blocking notifier
                # (e.g. network Slack call) does not stall the scheduler loop.
                t = threading.Thread(
                    target=self._notifier,
                    args=(event.reminder,),
                    daemon=True,
                )
                t.start()
            except Exception:
                log.exception(
                    "Could not start notifier thread for reminder %r",
                    event.reminder.get("name"),
                )

            # Skip rescheduling for one-shot reminders; remove from _live
            if is_oneshot:
                name = event.reminder.get("name")
                log.debug("One-shot reminder %r fired, not rescheduling", name)
                with self._lock:
                    if self._live.get(name) is event:
                        del self._live[name]
                continue

            # Re-schedule for next occurrence
            if event.reminder.get("at"):
                # Daily at-time: fire again at the same HH:MM tomorrow
                next_fire = self._next_at_fire(event.reminder)
            else:
                # Interval: anchor to now to avoid drift
                interval = self._parse_interval(event.reminder)
                next_fire = (now + interval) if interval else None

            if next_fire:
                next_event = _Event(
                    fire_at=next_fire,
                    reminder=deepcopy(event.reminder),
                )
                with self._lock:
                    name = event.reminder["name"]
                    # Only re-schedule if it hasn't been removed in the meantime
                    if name in self._live and self._live[name] is event:
                        self._live[name] = next_event
                        heapq.heappush(self._heap, next_event)
