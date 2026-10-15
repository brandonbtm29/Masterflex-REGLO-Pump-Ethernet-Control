"""Software Time and Volume dispensing for the REGLO.

The drive stays in its own continuous mode (it stopped accepting parameters reliably when
switched into time/volume mode over EtherNet/IP), so the app decides when to run and pause.
This module holds that decision logic with no Qt or network code, so it can be tested alone.

One cycle = dispense (for ``on_time`` seconds, or until ``volume`` has been pumped), then
pause for ``off_time`` seconds, repeated ``batch_total`` times (0 = until stopped).
Timing and volume start counting when the pump actually reports that it is running, so
spin-up delay doesn't shorten a dispense. If the pump is stopped from its own touchscreen
during a dispense, or never starts, the program gives up rather than restarting it later.

``tick`` is called from the communication thread about every 100 ms; the caller holds a
lock around it and around ``start``/``cancel``.
"""

TIME = 1
VOLUME = 2

IDLE = "idle"
WAITING = "waiting"  # run requested, pump not running yet
DISPENSING = "dispensing"
PAUSING = "pausing"
DONE = "done"

STOP_GRACE = 0.5  # s the pump may report "not running" mid-dispense before we treat it as stopped
SETTLE = 1.0  # s after a dispense starts during which "not running" readings are ignored
START_TIMEOUT = 5.0  # s to wait for the pump to start before giving up


class DispenseController:
    def __init__(self):
        self.state = IDLE
        self.mode = None
        self.on_time = self.volume = self.off_time = 0.0
        self.batch_total = 1
        self.batches_done = 0
        self.event = ""  # last notable thing that happened, for the log; cleared by take_event()
        self._t0 = self._v0 = 0.0
        self._waiting_since = None
        self._idle_since = None

    @property
    def active(self):
        """True while a Time/Volume program is running or pausing between dispenses."""
        return self.state in (WAITING, DISPENSING, PAUSING)

    @staticmethod
    def check(mode, *, on_time=0.0, volume=0.0, off_time=0.0, batch_total=1):
        """Return "" if the parameters can run, else a message for the user."""
        if mode == TIME and on_time <= 0:
            return "Time mode needs an On Time above 0 seconds."
        if mode == VOLUME and volume <= 0:
            return "Volume mode needs a Dispense Volume above 0."
        if off_time < 0:
            return "The Off/Interval time can't be negative."
        if batch_total < 0:
            return "Batch Total can't be negative (0 means repeat until stopped)."
        return ""

    def start(self, mode, *, on_time=0.0, volume=0.0, off_time=0.0, batch_total=1):
        """Arm a new program. The caller turns the run bit on."""
        error = self.check(mode, on_time=on_time, volume=volume, off_time=off_time, batch_total=batch_total)
        if error:
            raise ValueError(error)
        self.mode = mode
        self.on_time, self.volume, self.off_time = float(on_time), float(volume), float(off_time)
        self.batch_total = int(batch_total)
        self.batches_done = 0
        self.event = ""
        self._wait()

    def cancel(self):
        self.state = IDLE

    def take_event(self):
        event, self.event = self.event, ""
        return event

    def _wait(self):
        self.state = WAITING
        self._waiting_since = None

    def _give_up(self, why):
        self.state = IDLE
        self.event = why
        return False

    def remaining(self, now, cum_vol, flow_per_second=None):
        """Seconds left in the current dispense, or None if unknown or not dispensing."""
        if self.state != DISPENSING:
            return None
        if self.mode == TIME:
            return max(0.0, self.on_time - (now - self._t0))
        if flow_per_second and flow_per_second > 0:
            return max(0.0, (self.volume - (cum_vol - self._v0)) / flow_per_second)
        return None

    def progress(self):
        """Batch progress for the dashboard, e.g. "2/5" or "3/∞"."""
        total = self.batch_total if self.batch_total else "∞"
        return f"{self.batches_done}/{total}"

    def tick(self, now, cum_vol, running):
        """Advance the program.

        ``now`` is a monotonic time in seconds, ``cum_vol`` the pump's cumulative volume and
        ``running`` whether the pump reports that it is running. Returns True to turn the run
        bit on, False to turn it off, or None to leave it as it is.
        """
        if self.state == WAITING:
            if running:
                self._t0, self._v0 = now, cum_vol
                self._idle_since = None
                self.state = DISPENSING
                return None
            if self._waiting_since is None:
                self._waiting_since = now
            elif now - self._waiting_since >= START_TIMEOUT:
                return self._give_up(
                    "Program stopped: the pump didn't start. Is it in remote mode, with the head closed?"
                )
            return None

        if self.state == DISPENSING:
            if running or now - self._t0 < SETTLE:
                self._idle_since = None
            elif self._idle_since is None:
                self._idle_since = now
            elif now - self._idle_since >= STOP_GRACE:
                return self._give_up("Program stopped: the pump was stopped outside the app.")
            if self.mode == TIME:
                finished = now - self._t0 >= self.on_time
            else:
                finished = cum_vol - self._v0 >= self.volume
            if not finished:
                return None
            self.batches_done += 1
            if self.batch_total and self.batches_done >= self.batch_total:
                self.state = DONE
                self.event = f"Program finished: {self.progress()} dispenses."
                return False
            if self.off_time > 0:
                self._t0 = now
                self.state = PAUSING
                return False
            self._t0, self._v0 = now, cum_vol  # no pause: next dispense starts straight away
            return None

        if self.state == PAUSING and now - self._t0 >= self.off_time:
            self._wait()
            return True

        return None
