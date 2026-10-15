"""Software Time and Volume dispensing for the REGLO.

The drive stays in its own continuous mode (it stopped accepting parameters reliably when
switched into time/volume mode over EtherNet/IP), so the app decides when to run and pause.
This module holds that decision logic with no Qt or network code, so it can be tested alone.

One cycle = dispense (for ``on_time`` seconds, or until ``volume`` has been pumped), then
pause for ``off_time`` seconds, repeated ``batch_total`` times (0 = until stopped).
Timing and volume start counting when the pump actually reports that it is running, so
spin-up delay doesn't shorten a dispense.
"""

TIME = 1
VOLUME = 2

IDLE = "idle"
WAITING = "waiting"  # run requested, pump not running yet
DISPENSING = "dispensing"
PAUSING = "pausing"
DONE = "done"


class DispenseController:
    def __init__(self):
        self.state = IDLE
        self.mode = None
        self.on_time = self.volume = self.off_time = 0.0
        self.batch_total = 1
        self.batches_done = 0
        self._t0 = self._v0 = 0.0

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
        self.state = WAITING

    def cancel(self):
        self.state = IDLE

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
                self.state = DISPENSING
            return None

        if self.state == DISPENSING:
            if self.mode == TIME:
                finished = now - self._t0 >= self.on_time
            else:
                finished = cum_vol - self._v0 >= self.volume
            if not finished:
                return None
            self.batches_done += 1
            if self.batch_total and self.batches_done >= self.batch_total:
                self.state = DONE
                return False
            if self.off_time > 0:
                self._t0 = now
                self.state = PAUSING
                return False
            self._t0, self._v0 = now, cum_vol  # no pause: next dispense starts straight away
            return None

        if self.state == PAUSING and now - self._t0 >= self.off_time:
            self.state = WAITING
            return True

        return None
