"""Clock-time triggers: start a show at 10:00 PM, on the days you name."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from datetime import date, datetime

from PySide6.QtCore import QObject, QTimer

from ..config import ClockTrigger
from .base import CLOCK, TriggerSource

log = logging.getLogger(__name__)

POLL_MS = 1000


class ClockTriggerSource(TriggerSource):
    """Fire configured shows when the wall clock reaches their time.

    Polls at 1 Hz off the system clock rather than arming a timer for each
    trigger, so a machine that sleeps, or whose clock is stepped by NTP or by a
    daylight-saving change, picks the schedule straight back up instead of
    holding a timer that expires at the wrong moment.

    A trigger fires at most once per minute per day, and ``start()`` claims the
    current minute so relaunching the app at 10:00 PM does not immediately
    re-fire the 10:00 PM show.
    """

    source_name = CLOCK

    def __init__(
        self,
        triggers: Iterable[ClockTrigger] = (),
        *,
        now_fn: Callable[[], datetime] = datetime.now,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.triggers = list(triggers)
        self._now_fn = now_fn
        self._fired: dict[int, tuple[date, int, int]] = {}
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self.poll)

    def start(self) -> None:
        if not self.triggers:
            self.set_status("no clock triggers")
            return
        self._claim_current_minute()
        self._timer.start()
        self.set_status(self._describe())
        log.info("Clock triggers armed: %s", ", ".join(t.label for t in self.triggers))

    def stop(self) -> None:
        self._timer.stop()
        self.set_status("stopped")

    def poll(self) -> None:
        """Check the schedule once. Called on a timer; safe to call directly."""
        now = self._now_fn()
        for index, trigger in enumerate(self.triggers):
            if not trigger.matches(now):
                continue
            stamp = (now.date(), now.hour, now.minute)
            if self._fired.get(index) == stamp:
                continue
            self._fired[index] = stamp
            self.fire(trigger.show, detail=f"clock {trigger.at.strftime('%H:%M')}")

    def _claim_current_minute(self) -> None:
        now = self._now_fn()
        stamp = (now.date(), now.hour, now.minute)
        for index, trigger in enumerate(self.triggers):
            if trigger.matches(now):
                log.info("Clock trigger %r already due this minute; skipping it", trigger.label)
                self._fired[index] = stamp

    def _describe(self) -> str:
        count = len(self.triggers)
        return f"{count} clock trigger{'s' if count != 1 else ''} armed"
