"""
kim_scheduler.py
================================================================================
"""

import heapq
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
            interval = self._parse_interval(reminder)
            if interval is None:
                log.warning(
                    "Skipping reminder %r — invalid interval", reminder.get("name")
                )
                continue
            event = _Event(fire_at=now + interval, reminder=deepcopy(reminder))
            self._live[reminder["name"]] = event
            heapq.heappush(self._heap, event)

    @staticmethod
    def _parse_interval(reminder: dict) -> Optional[float]:
        """
        Convert interval_minutes to seconds.
        Supports:
          - int / float  → treated as minutes
          - "30m"        → 30 minutes
          - "2h"         → 2 hours
          - "1d"         → 1 day
        Returns None if the value is invalid.
        """
        raw = reminder.get("interval_minutes", 0)
        try:
            if isinstance(raw, (int, float)):
                return float(raw) * 60
            raw = str(raw).strip().lower()
            if raw.endswith("d"):
                return float(raw[:-1]) * 86400
            if raw.endswith("h"):
                return float(raw[:-1]) * 3600
            if raw.endswith("m"):
                return float(raw[:-1]) * 60
            return float(raw) * 60
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
        interval = self._parse_interval(reminder)
        if interval is None:
            raise ValueError(f"Invalid interval for reminder {name!r}")

        with self._lock:
            # Cancel any existing event for this name
            if name in self._live:
                self._live[name].cancelled = True

            event = _Event(
                fire_at=time.time() + interval,
                reminder=deepcopy(reminder),
            )
            self._live[name] = event
            heapq.heappush(self._heap, event)

        self._wakeup.set()  # wake scheduler to re-evaluate next fire time
        log.info("Added reminder %r (interval %ss)", name, interval)

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

    def update_reminder(self, reminder: dict) -> None:
        """Update an existing reminder in place (kim update)."""
        self.add_reminder(reminder)  # add_reminder handles replacement

    def enable_reminder(self, name: str) -> bool:
        """Re-enable a previously disabled reminder (kim enable)."""
        with self._lock:
            event = self._live.get(name)
            if event is None:
                return False
            event.reminder["enabled"] = True
        return True

    def disable_reminder(self, name: str) -> bool:
        """Disable a reminder without removing it (kim disable)."""
        return self.remove_reminder(name)

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
                self._wakeup.clear()

                with self._lock:
                    # Drain cancelled events from the top of the heap
                    while self._heap and self._heap[0].cancelled:
                        heapq.heappop(self._heap)

                    if not self._heap:
                        sleep_for = self._IDLE_SLEEP
                    else:
                        sleep_for = max(0.0, self._heap[0].fire_at - time.time())

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
            try:
                self._notifier(event.reminder)
            except Exception:
                log.exception(
                    "Notifier raised for reminder %r", event.reminder.get("name")
                )

            # Re-schedule this reminder for its next interval
            interval = self._parse_interval(event.reminder)
            if interval:
                next_event = _Event(
                    fire_at=event.fire_at
                    + interval,  # drift-free: add to last fire time
                    reminder=event.reminder,
                )
                with self._lock:
                    name = event.reminder["name"]
                    # Only re-schedule if it hasn't been removed in the meantime
                    if name in self._live and self._live[name] is event:
                        self._live[name] = next_event
                        heapq.heappush(self._heap, next_event)


# ══════════════════════════════════════════════════════════════════════════════
# Notifier helpers  (mirrors KIM's existing platform dispatch)
# ══════════════════════════════════════════════════════════════════════════════

from .notifications import notify


def platform_notifier(reminder: dict) -> None:
    """
    Cross-platform notification dispatcher.
    Drop this in wherever KIM currently calls notify-send / osascript / toast.
    """
    title = reminder.get("title", "KIM Reminder")
    message = reminder.get("message", "")
    urgency = reminder.get("urgency", "normal")
    # Use the full notify function with sound=False, slack_config=None
    notify(title, message, urgency, sound=False, slack_config=None)


# ══════════════════════════════════════════════════════════════════════════════
# Integration shim  — replace KIM's daemon startup with this
# ══════════════════════════════════════════════════════════════════════════════


def start_daemon(config: dict) -> KimScheduler:
    """
    Replaces the loop in kim.py that does:

        for reminder in enabled_reminders:
            t = threading.Thread(target=reminder_loop, args=(reminder,))
            t.daemon = True
            t.start()

    with:

        scheduler = start_daemon(config)

    Returns the running KimScheduler so kim.py can call stop() on SIGTERM.
    """
    scheduler = KimScheduler(config, platform_notifier)
    scheduler.start()
    return scheduler


# ══════════════════════════════════════════════════════════════════════════════
# Integration shim  — replace KIM's daemon startup with this
# ══════════════════════════════════════════════════════════════════════════════


def start_daemon(config: dict) -> KimScheduler:
    """
    Replaces the loop in kim.py that does:

        for reminder in enabled_reminders:
            t = threading.Thread(target=reminder_loop, args=(reminder,))
            t.daemon = True
            t.start()

    with:

        scheduler = start_daemon(config)

    Returns the running KimScheduler so kim.py can call stop() on SIGTERM.
    """
    scheduler = KimScheduler(config, platform_notifier)
    scheduler.start()
    return scheduler
