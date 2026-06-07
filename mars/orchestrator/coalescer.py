"""
ZoneCoalescer — per-zone debounce buffer for slow-path failure analysis.

Invariant: persist every failure at ingest; coalesce only the analysis.
A burst of K failures in a zone produces K `failures` rows but one
investigation → one diagnosis → one strategy run → one policy.

Debounce semantics:
  Each new slow failure in a zone extends the zone's window.
  When the zone goes quiet for COALESCE_WINDOW_SECONDS, the coalescer
  fires on_zone_ready(zone, trigger_event) exactly once, where
  trigger_event is the latest failure in the zone.

Zones are keyed independently — different zones coalesce on separate
timers and never block or delay each other.

Thread safety:
  ingest() is called from the sim/ingest thread.
  _zone_closed() fires from a daemon Timer thread.
  Both touch shared state; a single lock guards all mutations.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable

log = logging.getLogger(__name__)


class ZoneCoalescer:
    def __init__(
        self,
        window_sec: float,
        on_zone_ready: Callable[[str, dict[str, Any]], None],
    ):
        """
        window_sec    — debounce duration; each new failure extends the zone's timer.
        on_zone_ready — callback(zone, trigger_event) fired when a zone goes quiet.
                        Called from a daemon thread; use a queue for hand-off to
                        the processing thread.
        """
        self._window_sec   = window_sec
        self._on_zone_ready = on_zone_ready
        self._lock          = threading.Lock()
        # zone → list of slow failure events buffered in the current window
        self._buffers: dict[str, list[dict[str, Any]]] = {}
        # zone → active debounce timer
        self._timers: dict[str, threading.Timer] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest(self, event: dict[str, Any]) -> None:
        """
        Add a slow-path failure to the zone's buffer and extend its window.
        Thread-safe; may be called from any thread.
        """
        zone = event.get("zone") or "_unknown"
        timer = None
        with self._lock:
            self._buffers.setdefault(zone, []).append(event)
            # Cancel existing timer so the window restarts from now.
            existing = self._timers.pop(zone, None)
            if existing:
                existing.cancel()
            timer = threading.Timer(
                self._window_sec, self._zone_closed, args=[zone]
            )
            timer.daemon = True
            self._timers[zone] = timer
        timer.start()
        log.debug("[coalescer] zone=%s buffered (window=%.2fs)", zone, self._window_sec)

    def has_open_windows(self) -> bool:
        """Return True while any zone's debounce window is still counting down."""
        with self._lock:
            return bool(self._timers)

    def open_zone_count(self) -> int:
        with self._lock:
            return len(self._timers)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _zone_closed(self, zone: str) -> None:
        """
        Called by the timer thread when a zone's window expires.
        Emits exactly one on_zone_ready call with the latest buffered event.
        """
        with self._lock:
            events = self._buffers.pop(zone, [])
            self._timers.pop(zone, None)

        if not events:
            return

        trigger = events[-1]   # latest failure = representative trigger
        log.info(
            "[coalescer] zone=%s window closed: %d failure(s) → one analysis (trigger=%s)",
            zone, len(events), trigger.get("failure_id", "?"),
        )
        try:
            self._on_zone_ready(zone, trigger)
        except Exception:
            log.exception("[coalescer] on_zone_ready callback failed for zone=%s", zone)
