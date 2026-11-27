"""End one brew's measurements on device evidence or inactivity, using journal time."""
import math


def valid_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def device_stop(data):
    if data.get('code') == 40512 and data.get('kind') in ('completion_candidate', None):
        return 'program_end'
    if data.get('state') == 'idle' and data.get('kind') in ('state', None):
        return 'machine_idle'


class BrewWindow:
    idle_seconds = 30

    def __init__(self, pours=()):
        self.pours = pours
        self.started = False
        self.pouring = False
        self.reason = None
        self.ended_at = None
        self.last_update = self.last_read = None
        self.planned_until = 0
        self.state = None
        self.phases = set()
        self.high = {}

    @property
    def deadline(self):
        if self.last_update is None:
            return None
        return min(self.last_read, max(self.planned_until, self.last_update)) + self.idle_seconds

    def expire(self, now):
        deadline = self.deadline
        if not self.reason and deadline is not None and now >= deadline:
            self.close('no_update', deadline)

    def close(self, reason, at):
        if self.reason is None:
            self.reason, self.ended_at = reason, at

    def accept(self, event):
        if self.reason:
            return
        kind = event.get('kind')
        t = event.get('received_elapsed_s', event.get('elapsed_s'))
        if kind == 'session':
            self.pours = ((event.get('recipe') or {}).get('recipe') or {}).get('pours', [])
        if kind == 'tx_intent' and event.get('label') == 'start_commit':
            self.started = True
            if valid_number(t):
                self.last_update = self.last_read = t
        if kind == 'observation_ended':
            self.close(event.get('stop_reason', 'window_ended'), t)
            return
        if kind in ('error', 'disconnected'):
            self.close(kind, t)
            return
        if not self.started or kind != 'decoded' or not valid_number(t) or t < 0:
            return
        data = event.get('data')
        if not isinstance(data, dict) or (self.last_read is not None and t < self.last_read):
            return
        self.expire(t)
        if self.reason:
            return
        if self.last_read is None:
            self.last_update = self.last_read = t
        code, frame = data.get('code'), data.get('kind')
        stop = device_stop(data) if self.pouring else None
        if stop:
            self.close(stop, t)
        elif frame in ('state', None) and data.get('state'):
            self.last_read = t
            if self.state != data['state']:
                self.last_update, self.state = t, data['state']
        elif code in (40506, 40510, 40511) and frame in ('legacy_event', None):
            self.last_read = t
            phase = (code, data.get('payload_hex'))
            if phase not in self.phases:
                self.phases.add(phase)
                self.last_update = t
                if code == 40506 and not self.pouring:
                    # A normal grinder can run longer than 30 s with a flat scale.
                    # Allow one interval for grinding while readings still arrive.
                    self.planned_until = t + self.idle_seconds
                elif code == 40510:
                    self.pouring = True
                    self.planned_until = 0
                    self._stage(t, data.get('payload_hex'))
                elif code == 40511:
                    self.planned_until = 0
        elif frame in ('weight', None):
            for field in ('coffee_g', 'water_g'):
                value = data.get(field)
                if not valid_number(value) or not 0 <= value <= 2000:
                    continue
                self.last_read = t
                if self.pouring and round(value, 1) > self.high.get(field, -1):
                    self.high[field] = round(value, 1)
                    self.last_update = t

    def _stage(self, t, raw):
        if not isinstance(raw, str) or len(raw) != 8:
            return
        try:
            index = int.from_bytes(bytes.fromhex(raw), 'little')
        except ValueError:
            return
        if index < len(self.pours):
            pour = self.pours[index]
            volume, flow, pause = (pour.get(key) for key in ('volume', 'flowRate', 'pausing'))
            if all(valid_number(n) for n in (volume, flow, pause)) and flow > 0 and pause > 0:
                self.planned_until = t + volume / flow + pause
            else:
                self.planned_until = 0
