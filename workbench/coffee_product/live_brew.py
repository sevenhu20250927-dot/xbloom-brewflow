"""Project one xBloom journal into second-by-second readings for the workbench."""
from math import isfinite
from xbloom_bridge.observation import BrewWindow


class LiveBrew:
    def __init__(self):
        self.volumes = []
        self.bypass = 0
        self.origin = None
        self.elapsed = 0
        self.closed = False
        self.window = BrewWindow()
        self.latest_at = None
        self.stages = []
        self.points = []
        self.water = self.water_at = self.cup = self.cup_at = None
        self.stage_baseline = self.last_flow_at = None
        self.counter_reset = False

    def accept(self, event):
        if self.closed:
            return
        kind = event.get("kind")
        self.window.accept(event)
        if self.window.reason:
            self.closed = True
            if self.origin is not None and self.window.reason == "program_end":
                self.elapsed = int(self.window.ended_at - self.origin)
            return
        if kind == "session":
            payload = event.get("recipe") or {}
            self.volumes = [p["volume"] for p in (payload.get("recipe") or {}).get("pours", [])]
            self.bypass = payload.get("bypassMl", 0)
        if not self.window.started or kind != "decoded":
            return
        data = event.get("data")
        t = event.get("received_elapsed_s", event.get("elapsed_s"))
        if not isinstance(data, dict) or type(t) not in (int, float) or not isfinite(t) or t < 0:
            return
        if self.latest_at is not None and t < self.latest_at:
            return
        self.latest_at = t
        if data.get("kind") == "legacy_event" and data.get("code") == 40510:
            raw = data.get("payload_hex", "")
            try:
                index = int.from_bytes(bytes.fromhex(raw), "little") + 1 if len(raw) == 8 else None
            except (TypeError, ValueError):
                index = None
            if self.origin is None:
                self.origin = t
                if self.water != 0:
                    self.water = self.water_at = None
            if index is not None and 1 <= index <= len(self.volumes):
                if not self.stages or index > self.stages[-1][1]:
                    self.stages.append([int(t - self.origin), index])
                    self.stage_baseline = self.water if self.water_at is not None and 0 <= t-self.water_at <= 1 else None
        if self.origin is not None:
            self.elapsed = max(self.elapsed, int(t - self.origin))
        if data.get("kind") != "weight":
            return
        is_water = "water_g" in data
        value = data.get("water_g" if is_water else "coffee_g")
        if type(value) not in (int, float) or not isfinite(value) or not 0 <= value <= 2000:
            return
        if is_water:
            if self.counter_reset:
                return
            if self.origin is not None and self.water is not None:
                if value < self.water:
                    self.counter_reset = True
                    if self.points and self.points[-1][0] == self.elapsed:
                        self.points[-1][3] = None
                    return
                if value > self.water:
                    self.last_flow_at = t
            self.water, self.water_at = value, t
        else:
            self.cup, self.cup_at = value, t
        if self.origin is None:
            return
        second = int(t - self.origin)
        if not self.points or self.points[-1][0] < second:
            self.points.append([second, None, None, None])
        point = self.points[-1]
        if point[0] != second:
            return
        point[1 if is_water else 2] = round(value, 1)
        # Pair only readings from this second. No extrapolation across gaps,
        # scale resets, or the ambiguous through-bed/bypass transition.
        point[3] = None
        if (point[1] is not None and point[2] is not None and not self.counter_reset
                and not (self.bypass and self.water >= sum(self.volumes)) and self.water >= self.cup):
            point[3] = round(self.water - self.cup, 1)

    def snapshot(self):
        points = [row.copy() for row in self.points]
        return {"elapsed_s": self.elapsed if self.origin is not None else None,
                "stages": list(self.stages), "volumes": self.volumes, "bypass_ml": self.bypass,
                "points": points, "closed": self.closed, "stop_reason": self.window.reason,
                "counter_reset": self.counter_reset,
                "flowing": bool(not self.closed and not self.counter_reset and self.last_flow_at is not None
                                and self.origin + self.elapsed - self.last_flow_at < 1.5),
                "stage_ml": (round(self.water - self.stage_baseline, 1)
                             if self.stage_baseline is not None and not self.counter_reset
                             and not (self.bypass and self.water > sum(self.volumes)) else None)}
