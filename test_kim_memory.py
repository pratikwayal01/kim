"""
test_kim_memory.py — Memory scale tests for KIM reminder daemon
================================================================
Tests memory usage across:
  1. Config parsing at scale (10 → 10,000 reminders)
  2. OLD vs NEW scheduler head-to-head (thread-per-reminder vs heapq)
  3. Memory leak detection over repeated cycles
  4. Peak vs steady-state memory
  5. Large config field payloads

Run:
    python test_kim_memory.py

Requirements:
    pip install psutil   (optional but preferred — falls back to tracemalloc only)

Place kim.py in the same directory for the KimScheduler comparison test.
"""

import gc
import json
import os
import sys
import tempfile
import threading
import time
import tracemalloc
from dataclasses import dataclass, field
from typing import List, Optional

# ── optional KimScheduler (from kim.scheduler) ───────────────────────────────
try:
    from kim.scheduler import KimScheduler

    _HAS_KIM = True
except Exception as _e:
    _HAS_KIM = False
    KimScheduler = None
    print(
        f"[warn] kim.scheduler not found — scheduler comparison test will be skipped ({_e})\n"
    )

# ── optional psutil ────────────────────────────────────────────────────────────
try:
    import psutil

    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False
    print("[warn] psutil not found — process-level RSS measurements disabled.")
    print("       Install with: pip install psutil\n")


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════
import platform

HLINE = "-" if platform.system() == "Windows" else "─"
DOUBLE_LINE = "=" if platform.system() == "Windows" else "═"
EM_DASH = "--" if platform.system() == "Windows" else "—"


def ascii_table_line(line):
    """Replace box drawing characters with ASCII equivalents."""
    replacements = {
        "─": "-",
        "│": "|",
        "┌": "+",
        "┐": "+",
        "└": "+",
        "┘": "+",
        "├": "+",
        "┤": "+",
        "┬": "+",
        "┴": "+",
        "┼": "+",
    }
    for k, v in replacements.items():
        line = line.replace(k, v)
    return line


TABLE_LINE = ascii_table_line if platform.system() == "Windows" else lambda x: x


def rss_mb() -> Optional[float]:
    """Current process RSS in MB (requires psutil)."""
    if _HAS_PSUTIL:
        return psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
    return None


def fmt_mb(value: Optional[float]) -> str:
    return f"{value:.2f} MB" if value is not None else "N/A (no psutil)"


@dataclass
class MemSample:
    label: str
    rss_before: Optional[float]
    rss_after: Optional[float]
    tracemalloc_peak_kb: float
    tracemalloc_current_kb: float
    duration_s: float
    extras: dict = field(default_factory=dict)

    @property
    def rss_delta(self) -> Optional[float]:
        if self.rss_before is not None and self.rss_after is not None:
            return self.rss_after - self.rss_before
        return None

    def report(self) -> str:
        import platform

        if platform.system() == "Windows":
            # Replace problematic Unicode characters with ASCII equivalents
            mapping = {
                "─": "-",
                "✓": "OK",
                "✗": "ERROR",
                "·": ".",
                "●": "*",
                "○": "o",
                "⚠": "!",
                "━": "-",
                "►": ">",
            }

            def replace_chars(s):
                for k, v in mapping.items():
                    s = s.replace(k, v)
                return s
        else:

            def replace_chars(s):
                return s

        lines = [
            f"\n{'─' * 60}",
            f"  {self.label}",
            f"{'─' * 60}",
            f"  RSS before     : {fmt_mb(self.rss_before)}",
            f"  RSS after      : {fmt_mb(self.rss_after)}",
            f"  RSS delta      : {fmt_mb(self.rss_delta)}",
            f"  TM peak        : {self.tracemalloc_peak_kb:.1f} KB",
            f"  TM current     : {self.tracemalloc_current_kb:.1f} KB",
            f"  Duration       : {self.duration_s:.3f}s",
        ]
        for k, v in self.extras.items():
            lines.append(f"  {k:<15}: {v}")
        # Apply replacements only on Windows
        if platform.system() == "Windows":
            lines = [replace_chars(line) for line in lines]
        return "\n".join(lines)


def measure(label: str, fn, *args, **kwargs) -> MemSample:
    """Run fn(*args, **kwargs) and capture memory metrics."""
    gc.collect()
    rss_before = rss_mb()
    tracemalloc.start()
    t0 = time.perf_counter()

    result = fn(*args, **kwargs)

    duration = time.perf_counter() - t0
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    rss_after = rss_mb()

    sample = MemSample(
        label=label,
        rss_before=rss_before,
        rss_after=rss_after,
        tracemalloc_peak_kb=peak / 1024,
        tracemalloc_current_kb=current / 1024,
        duration_s=duration,
    )
    return sample, result


# ══════════════════════════════════════════════════════════════════════════════
# KIM-replica helpers  (mirrors kim.py patterns without importing it)
# ══════════════════════════════════════════════════════════════════════════════


def make_reminder(index: int, msg_len: int = 60) -> dict:
    """Produce a reminder dict that looks exactly like KIM's config schema."""
    return {
        "name": f"reminder-{index:05d}",
        "interval_minutes": 30 + (index % 1440),
        "title": f"Reminder #{index}",
        "message": "x" * msg_len,
        "urgency": ["low", "normal", "critical"][index % 3],
        "enabled": index % 7 != 0,  # ~14 % disabled
    }


def build_config(n: int, msg_len: int = 60) -> dict:
    return {
        "reminders": [make_reminder(i, msg_len) for i in range(n)],
        "sound": True,
        "slack": {"enabled": False},
    }


def parse_config(config: dict) -> List[dict]:
    """Replica of KIM's config parsing: returns list of enabled reminders."""
    return [r for r in config["reminders"] if r.get("enabled", True)]


def write_config_file(n: int, msg_len: int = 60) -> str:
    """Write a JSON config to a temp file and return its path."""
    cfg = build_config(n, msg_len)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(cfg, f)
        return f.name


def load_config_file(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


# ── Thread replica ─────────────────────────────────────────────────────────────


class ReminderThread(threading.Thread):
    """Mimics KIM's per-reminder daemon thread (sleeps, never fires for tests)."""

    def __init__(self, reminder: dict):
        super().__init__(daemon=True)
        self.reminder = reminder
        self._stop_event = threading.Event()

    def run(self):
        interval = self.reminder["interval_minutes"] * 60
        while not self._stop_event.wait(timeout=interval):
            pass  # would send notification here

    def stop(self):
        self._stop_event.set()


# ══════════════════════════════════════════════════════════════════════════════
# TEST CASES
# ══════════════════════════════════════════════════════════════════════════════

results: List[MemSample] = []

# ── Test 1: Config object construction at scale ────────────────────────────────


def test_config_construction_scale():
    print("\n[TEST 1] Config object construction at scale")
    sizes = [10, 100, 500, 1_000, 5_000, 10_000]
    for n in sizes:
        sample, cfg = measure(f"build_config({n} reminders)", build_config, n)
        sample.extras["n_reminders"] = n
        sample.extras["n_enabled"] = len(parse_config(cfg))
        results.append(sample)
        print(sample.report())
        del cfg
        gc.collect()


# ── Test 2: Config JSON serialise / deserialise ────────────────────────────────


def test_config_json_io():
    print("\n[TEST 2] Config JSON round-trip (write + read from disk)")
    sizes = [100, 1_000, 5_000]
    tmp_files = []
    for n in sizes:
        path = write_config_file(n)
        tmp_files.append(path)

        sample, loaded = measure(f"load_config({n} reminders)", load_config_file, path)
        sample.extras["n_reminders"] = n
        sample.extras["file_size_kb"] = os.path.getsize(path) / 1024
        results.append(sample)
        print(sample.report())
        del loaded
        gc.collect()

    for p in tmp_files:
        os.unlink(p)


# ── Test 3: OLD vs NEW scheduler head-to-head ─────────────────────────────────


def test_thread_overhead():
    """
    Head-to-head memory comparison:
      OLD — one thread per reminder (ReminderThread)
      NEW — single heapq scheduler thread (KimScheduler)
    """
    print("\n[TEST 3] OLD (threads) vs NEW (heapq scheduler) — head-to-head")
    thread_counts = [10, 50, 100, 200, 500]

    # ── OLD: thread-per-reminder ───────────────────────────────────────────
    print("\n  ▶ OLD: thread-per-reminder")
    for n in thread_counts:
        reminders = [make_reminder(i) for i in range(n)]
        threads = []

        gc.collect()
        rss_before = rss_mb()
        tracemalloc.start()
        t0 = time.perf_counter()

        for r in reminders:
            t = ReminderThread(r)
            t.start()
            threads.append(t)

        duration = time.perf_counter() - t0
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        rss_after = rss_mb()

        sample = MemSample(
            label=f"[OLD] {n} threads",
            rss_before=rss_before,
            rss_after=rss_after,
            tracemalloc_peak_kb=peak / 1024,
            tracemalloc_current_kb=current / 1024,
            duration_s=duration,
        )
        rss_per = (sample.rss_delta / n) if sample.rss_delta else None
        sample.extras["n_reminders"] = n
        sample.extras["rss_per_reminder"] = fmt_mb(rss_per)
        results.append(sample)
        print(sample.report())

        for t in threads:
            t.stop()
        for t in threads:
            t.join(timeout=1)
        del threads
        gc.collect()

    # ── NEW: heapq KimScheduler ────────────────────────────────────────────
    print("\n  ▶ NEW: heapq KimScheduler")
    if not _HAS_KIM:
        print("  (skipped — kim.py not found)")
        return

    def _noop_notifier(reminder):
        pass  # don't actually send notifications during test

    for n in thread_counts:
        config = build_config(n)

        gc.collect()
        rss_before = rss_mb()
        tracemalloc.start()
        t0 = time.perf_counter()

        scheduler = KimScheduler(config, _noop_notifier)
        scheduler.start()

        duration = time.perf_counter() - t0
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        rss_after = rss_mb()

        sample = MemSample(
            label=f"[NEW] {n} reminders (heapq)",
            rss_before=rss_before,
            rss_after=rss_after,
            tracemalloc_peak_kb=peak / 1024,
            tracemalloc_current_kb=current / 1024,
            duration_s=duration,
        )
        rss_per = (sample.rss_delta / n) if sample.rss_delta else None
        sample.extras["n_reminders"] = n
        sample.extras["rss_per_reminder"] = fmt_mb(rss_per)
        results.append(sample)
        print(sample.report())

        scheduler.stop()
        del scheduler
        gc.collect()

    # ── Print comparison table ─────────────────────────────────────────────
    print(TABLE_LINE("\n  ┌─────────────────────────────────────────────────────────┐"))
    print(TABLE_LINE("  │  HEAD-TO-HEAD SUMMARY (RSS delta)                       │"))
    print(TABLE_LINE("  ├──────────┬──────────────┬──────────────┬────────────────┤"))
    print(TABLE_LINE("  │ Reminders│ OLD (threads)│ NEW (heapq)  │ Savings        │"))
    print(TABLE_LINE("  ├──────────┼──────────────┼──────────────┼────────────────┤"))

    old_results = {
        s.extras["n_reminders"]: s for s in results if s.label.startswith("[OLD]")
    }
    new_results = {
        s.extras["n_reminders"]: s for s in results if s.label.startswith("[NEW]")
    }

    for n in thread_counts:
        old = old_results.get(n)
        new = new_results.get(n)
        old_str = fmt_mb(old.rss_delta) if old else "N/A"
        new_str = fmt_mb(new.rss_delta) if new else "N/A"
        if old and new and old.rss_delta and new.rss_delta and old.rss_delta > 0:
            savings = (1 - new.rss_delta / old.rss_delta) * 100
            sav_str = f"{savings:.0f}% less"
        else:
            sav_str = "N/A"
        print(f"  │ {n:<8} │ {old_str:>12} │ {new_str:>12} │ {sav_str:<14} │")

    print(TABLE_LINE("  └──────────┴──────────────┴──────────────┴────────────────┘"))


# ── Test 4: Memory leak detection — repeated parse cycles ─────────────────────


def test_memory_leak_detection():
    """
    Repeats config parse + filter CYCLES times. RSS should not grow after
    the first few warm-up iterations if there are no leaks.
    """
    print("\n[TEST 4] Leak detection — repeated parse cycles (500 reminders)")
    CYCLES = 200
    N = 500
    cfg = build_config(N)
    rss_snapshots = []

    gc.collect()
    for i in range(CYCLES):
        enabled = parse_config(cfg)
        _ = [r["name"] for r in enabled]  # simulate processing
        del enabled
        if i % 25 == 0:
            gc.collect()
            rss_snapshots.append((i, rss_mb()))

    rss_first = rss_snapshots[0][1]
    rss_last = rss_snapshots[-1][1]

    if rss_first is not None and rss_last is not None:
        drift = rss_last - rss_first
        verdict = "✅ STABLE" if abs(drift) < 1.0 else "⚠️  POSSIBLE LEAK"
    else:
        drift = None
        verdict = "N/A (no psutil)"

    print(f"\n  Cycles run       : {CYCLES}")
    print(f"  Reminder count   : {N}")
    print(f"  RSS at cycle 0   : {fmt_mb(rss_first)}")
    print(f"  RSS at cycle {CYCLES - 1:>3}  : {fmt_mb(rss_last)}")
    print(f"  RSS drift        : {fmt_mb(drift)}")
    print(f"  Verdict          : {verdict}")

    if rss_snapshots[0][1] is not None:
        print("\n  RSS timeline:")
        for cycle, rss in rss_snapshots:
            bar = "█" * int((rss - rss_first + 5) * 4) if rss_first else ""
            print(f"    cycle {cycle:>3}  {rss:.2f} MB  {bar}")


# ── Test 5: Large message payloads ────────────────────────────────────────────


def test_large_payload():
    """
    Simulates reminders with very long message strings (e.g. templated content).
    Tests whether KIM holds these in memory efficiently.
    """
    print("\n[TEST 5] Large message payload per reminder")
    msg_sizes = [100, 1_000, 10_000, 100_000]
    N = 100  # fixed reminder count, vary message size

    for msg_len in msg_sizes:
        sample, cfg = measure(
            f"{N} reminders × {msg_len}-char message", build_config, N, msg_len
        )
        total_payload_kb = (N * msg_len) / 1024
        sample.extras["total_payload"] = f"{total_payload_kb:.1f} KB"
        sample.extras["msg_len"] = msg_len
        results.append(sample)
        print(sample.report())
        del cfg
        gc.collect()


# ── Test 6: Concurrent config access ──────────────────────────────────────────


def test_concurrent_config_access():
    """
    Multiple threads reading the config simultaneously (as would happen if
    the daemon and a CLI command access config at the same time).
    """
    print("\n[TEST 6] Concurrent config reads (16 threads × 1,000 reminders)")
    N_READERS = 16
    N_REMINDERS = 1_000
    cfg = build_config(N_REMINDERS)
    errors = []
    barrier = threading.Barrier(N_READERS)

    def reader_task():
        barrier.wait()  # all start simultaneously
        try:
            enabled = parse_config(cfg)
            assert len(enabled) > 0
        except Exception as e:
            errors.append(e)

    gc.collect()
    rss_before = rss_mb()
    tracemalloc.start()
    t0 = time.perf_counter()

    threads = [threading.Thread(target=reader_task) for _ in range(N_READERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    duration = time.perf_counter() - t0
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    rss_after = rss_mb()

    sample = MemSample(
        label=f"concurrent config reads ({N_READERS} threads)",
        rss_before=rss_before,
        rss_after=rss_after,
        tracemalloc_peak_kb=peak / 1024,
        tracemalloc_current_kb=current / 1024,
        duration_s=duration,
    )
    sample.extras["errors"] = len(errors)
    sample.extras["thread_errors"] = str(errors) if errors else "none"
    results.append(sample)
    print(sample.report())


# ══════════════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════════════


def print_summary():
    print("\n" + DOUBLE_LINE * 60)
    print("  MEMORY TEST SUMMARY")
    print(DOUBLE_LINE * 60)
    print(f"  {'Test':<42} {'RSS Δ':>10}  {'TM Peak':>10}")
    print(f"  {HLINE * 42} {HLINE * 10}  {HLINE * 10}")
    for s in results:
        rss_str = fmt_mb(s.rss_delta) if s.rss_delta is not None else "N/A"
        print(f"  {s.label:<42} {rss_str:>10}  {s.tracemalloc_peak_kb:>7.1f} KB")
    print(DOUBLE_LINE * 60)

    if not _HAS_PSUTIL:
        print("\n  💡 Install psutil for RSS-level measurements:")
        print("     pip install psutil")


# ══════════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print(f"  KIM {EM_DASH} Memory Scale Tests")
    print(f"  Python {sys.version.split()[0]}  |  psutil: {_HAS_PSUTIL}")
    print("=" * 60)

    test_config_construction_scale()
    test_config_json_io()
    test_thread_overhead()
    test_memory_leak_detection()
    test_large_payload()
    test_concurrent_config_access()

    print_summary()
