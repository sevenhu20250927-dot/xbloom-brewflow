"""Offline xBloom codecs; no transport, retries, or machine actions.

Command encoding is adapted from ryunana/xbloom-studio-recipe-skill 1.3.2,
scripts/xbloom_proto.py (MIT, Copyright 2026 chengway.wang; see
PROTOCOL_LICENSE.txt). State/weight interpretations follow
Janczykkkko/xbloom-ble, xbloom_ble/telemetry.py. Those interpretations are
provisional until checked on the connected device/firmware. CRC validity is
not evidence that a command was accepted or a physical operation completed.
"""
from __future__ import annotations

from decimal import Decimal, DecimalException
import json
import math
import os
import stat
import struct

SERVICE_UUID = "0000e0ff-3c17-d293-8e48-14fe2e4da212"
CHAR_COMMAND = "0000ffe1-0000-1000-8000-00805f9b34fb"
CHAR_STATUS = "0000ffe2-0000-1000-8000-00805f9b34fb"
HEADER = b"\x58\x02\x07"
STATE_NAMES = {
    0x01: "idle", 0x0c: "no_water", 0x0f: "no_beans",
    0x10: "brewing", 0x1d: "loading", 0x1e: "awaiting_confirm",
    0x1f: "armed", 0x22: "starting", 0x23: "brewing", 0x24: "ready",
    0x25: "slots_saved", 0x3b: "brewing", 0x41: "complete",
    0x43: "saving_slots",
}


class ProtocolError(ValueError):
    pass


def crc16(data: bytes) -> int:
    """CRC-16/KERMIT: reflected 0x1021, initial/final xor zero."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return crc & 0xffff


class FrameAssembler:
    """Reassemble notifications, retaining bad-CRC full frames for diagnostics.

    Invalid headers/lengths are discarded; callers must persist notification
    bytes *before* feeding this assembler. At most max_frame_length bytes of
    an incomplete frame remain buffered. A complete CRC-valid later frame
    permits recovery from an earlier corrupt, plausible length.
    """

    def __init__(self, max_frame_length: int = 4096):
        if not 12 <= max_frame_length <= 65536:
            raise ValueError("invalid frame size limit")
        self.max_frame_length = max_frame_length
        self.buffer = bytearray()
        self.discarded_bytes = 0

    def _discard(self, count: int) -> None:
        self.discarded_bytes += count
        del self.buffer[:count]

    def feed(self, data: bytes) -> list[bytes]:
        self.buffer.extend(data)
        result = []
        while self.buffer:
            pos = self.buffer.find(HEADER)
            if pos < 0:
                # Preserve a potentially split header, not an arbitrary suffix.
                keep = 2 if self.buffer.endswith(HEADER[:2]) else int(self.buffer.endswith(HEADER[:1]))
                self._discard(len(self.buffer) - keep)
                break
            if pos:
                self._discard(pos)
            if len(self.buffer) < 9:
                break
            length = struct.unpack_from("<I", self.buffer, 5)[0]
            if not 12 <= length <= self.max_frame_length:
                self._discard(1)
                continue
            if len(self.buffer) < length:
                recovered = False
                candidate = self.buffer.find(HEADER, 3)
                while candidate >= 0 and len(self.buffer) - candidate >= 12:
                    n = struct.unpack_from("<I", self.buffer, candidate + 5)[0]
                    if 12 <= n <= self.max_frame_length and candidate + n <= len(self.buffer):
                        raw = bytes(self.buffer[candidate:candidate + n])
                        if crc16(raw[:-2]) == int.from_bytes(raw[-2:], "little"):
                            self._discard(candidate)
                            recovered = True
                            break
                    candidate = self.buffer.find(HEADER, candidate + 3)
                if recovered:
                    continue
                break
            frame = bytes(self.buffer[:length])
            result.append(frame)
            if crc16(frame[:-2]) != int.from_bytes(frame[-2:], "little"):
                # A corrupt length may have swallowed a later frame or its
                # partial header. Keep searching from the next byte, rather
                # than trusting that length as the next frame boundary.
                self._discard(1)
            else:
                del self.buffer[:length]
        return result


def decode_frame(packet: bytes) -> dict:
    """Validate a full notification and return observations, never a verdict."""
    raw = bytes(packet)
    if len(raw) < 12 or raw[:3] != HEADER:
        raise ProtocolError("invalid notification header or truncated frame")
    if struct.unpack_from("<I", raw, 5)[0] != len(raw):
        raise ProtocolError("notification length mismatch")
    if crc16(raw[:-2]) != int.from_bytes(raw[-2:], "little"):
        raise ProtocolError("notification CRC mismatch")
    payload = raw[10:-2]
    event = {
        "kind": "echo_or_unknown", "code": int.from_bytes(raw[3:5], "little"),
        "type": raw[3], "subtype": raw[4], "marker": raw[9],
        "raw_hex": raw.hex(), "payload_hex": payload.hex(),
    }
    # Unknown markers are retained, not decoded using guessed offsets.
    if raw[9] != 0xc1:
        return event
    if raw[3] == 0x57 and payload:
        state = payload[0]
        event.update(kind="state", state=STATE_NAMES.get(state, f"unknown_0x{state:02x}"),
                     state_code=state, interpretation="upstream_provisional")
        if state in (0x24, 0x41):
            event["completion_candidate"] = True
    elif raw[3] in (0x4b, 0x15):
        field = "water_g" if raw[3] == 0x4b else "coffee_g"
        event.update(kind="weight", interpretation="upstream_provisional", **{field: None})
        if len(payload) < 4:
            event["reading_error"] = "truncated_float32"
        else:
            value = struct.unpack_from("<f", payload)[0]
            grams = value * (0.001 if raw[3] == 0x4b else 1)
            event["float32_hex"] = payload[:4].hex()
            if math.isfinite(grams) and 0 <= grams <= 2000:
                event[field] = grams
            else:
                event["reading_error"] = "nonfinite_or_out_of_range"
    elif raw[3] == 0x49:
        event.update(kind="machine_info", interpretation="upstream_provisional")
        for name, begin, end in (("serial", 0, 13), ("firmware", 19, 29)):
            if len(payload) >= end:
                event[name] = payload[begin:end].decode("ascii", errors="replace").strip("\0 ")
        if len(payload) >= 34:
            event["water_sensor_raw"] = payload[33]
        if len(payload) >= 37:
            source = payload[36]
            event["water_source_raw"] = source
            event["water_source"] = {0: "tank", 1: "plumbed"}.get(source, "unknown")
            if source == 0 and payload[33] in (0, 1):
                event["water_ok"] = bool(payload[33])
        if len(payload) >= 38:
            event["grind_raw"] = payload[37]
            grind = payload[37] - 30
            event["grind_reported"] = grind if 1 <= grind <= 80 else None
            event["grind_semantics"] = "reported_value_not_confirmed_recipe_or_physical_position"
        if len(payload) >= 55:
            mode_bytes = payload[51:55]
            event["mode_raw"] = mode_bytes.hex()
            event["mode"] = {b"\x91\x32\x78\x56": "Auto", b"\0\0\0\0": "Pro"}.get(mode_bytes, "unknown")
    elif event["code"] == 40512:
        event.update(kind="completion_candidate", completion_candidate=True,
                     interpretation="legacy_RD_ENJOY_unverified_on_current_firmware")
    elif event["code"] in (40506, 40510, 40511, 40519, 40522):
        event.update(kind="legacy_event", event_name={40506: "grinding_report", 40510: "pour_report", 40511: "stopped",
                     40519: "stopped", 40522: "no_water"}[event["code"]],
                     interpretation="upstream_provisional")
    return event


def _command(code: int, payload: bytes = b"") -> bytes:
    body = b"\x58\x01\x01" + struct.pack("<HI", code, 12 + len(payload)) + b"\x01" + payload
    return body + struct.pack("<H", crc16(body))


def handshake_frame() -> bytes:
    return _command(8100, struct.pack("<ii", 185, 1))


def status_query_frame() -> bytes:
    """0x56 also means BACK HOME in the first source: NOT a read-only query."""
    return _command(0x1f56)


def start_frame() -> bytes:
    """Explicit commit may start grinding/brewing; never a preparation frame."""
    return _command(8002)


def cancel_frame() -> bytes:
    """Second repository's explicit cancel; current-device verification pending."""
    return _command(0x9e47)


MAX_RECIPE_BYTES = 65536
_FLOW_BYTES = {3: 30, 3.1: 31, 3.2: 32, 3.3: 33, 3.4: 34, 3.5: 35}


def _exact_keys(value, expected, path: str, optional=()) -> None:
    if type(value) is not dict:
        raise ProtocolError(f"{path} must be an object")
    missing = sorted(set(expected) - value.keys())
    extra = sorted(repr(key) for key in value.keys() - set(expected) - set(optional))
    if missing or extra:
        raise ProtocolError(f"{path}: missing fields {missing}; unknown fields {extra}")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _json_float(token: str) -> float:
    try:
        value = float(token)
        exact_decimal = math.isfinite(value) and Decimal(token) == Decimal(str(value))
    except (DecimalException, ValueError, OverflowError) as exc:
        raise ProtocolError("JSON decimal cannot be represented") from exc
    # JSON decimals must not become a different decimal when converted to float.
    # E.g. 3.0000000000000001 must not silently become the allowed flow 3.0.
    if not exact_decimal:
        raise ProtocolError("JSON number loses decimal precision or is nonfinite")
    return value


def _reject_constant(token: str):
    raise ProtocolError(f"nonfinite JSON number is not allowed: {token}")


def load_recipe(path) -> dict:
    """Read a bounded UTF-8 file and enforce the same contract as the encoder.

    This is the file entry point for preview/load/brew. No defaults, coercion,
    unknown fields or duplicate keys; the optional bypass pair is absent/off
    for legacy recipes. Never opens a Bluetooth connection.
    """
    try:
        # Reject file-descriptor integers instead of letting open() consume and
        # close a caller-owned descriptor (including stdin).
        path = os.fspath(path)
        # Nonblocking open avoids hanging on a FIFO supplied instead of a file;
        # fstat checks the opened object, not a racy pre-open path lookup.
        def opener(name, flags):
            return os.open(name, flags | getattr(os, "O_NONBLOCK", 0))

        with open(path, "rb", opener=opener) as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ProtocolError("recipe must be a regular file")
            raw = stream.read(MAX_RECIPE_BYTES + 1)
    except ProtocolError:
        raise
    except (OSError, ValueError, TypeError, RecursionError, OverflowError) as exc:
        raise ProtocolError(f"cannot read recipe: {exc}") from exc
    return parse_recipe(raw)


def parse_recipe(raw: bytes) -> dict:
    """Shared strict document boundary for files and HTTP; never sends commands."""
    if type(raw) is not bytes:
        raise ProtocolError("recipe document must be UTF-8 bytes")
    if len(raw) > MAX_RECIPE_BYTES:
        raise ProtocolError("recipe exceeds 64 KiB")
    try:
        recipe = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                            parse_float=_json_float, parse_constant=_reject_constant)
    except ProtocolError:
        raise
    except (ValueError, RecursionError, OverflowError) as exc:
        raise ProtocolError(f"cannot parse recipe: {exc}") from exc
    build_recipe_frames(recipe)
    return recipe


def _integer(value, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ProtocolError(f"{name} must be an integer in {minimum}..{maximum}")
    return value


def build_recipe_frames(recipe: dict) -> list[tuple[str, bytes]]:
    """Encode reviewed legacy recipe JSON without silently adjusting any value.

    Supports grinder-off and legacy grinder-on recipes, Omni dripper, integer
    dose and volumes. Cup 110/90 is preserved as the first source's Omni range,
    NOT labeled preheat temperature. Unsupported recipes fail before writes.
    Returns only dose/cup/recipe; no mode, home, handshake, start or preset write.
    """
    try:
        _exact_keys(recipe, ("cupType", "doseGrams", "recipe"), "$",
                    optional=("bypassMl", "bypassTempC"))
        if type(recipe["cupType"]) is not str or recipe["cupType"] != "xdripper":
            raise ProtocolError("only reviewed Omni xdripper cupType is supported")
        dose = _integer(recipe["doseGrams"], "doseGrams", 5, 18)
        bypass_volume, bypass_temp = 0, 0
        if "bypassMl" in recipe or "bypassTempC" in recipe:
            if "bypassMl" not in recipe or "bypassTempC" not in recipe:
                raise ProtocolError("bypassMl and bypassTempC must be provided together")
            bypass_volume = _integer(recipe["bypassMl"], "bypassMl", 0, 500)
            # Supported project scope: normal Celsius setpoints only. No inferred
            # RT/BP bypass support. Explicit off is the pair 0/0.
            bypass_temp = _integer(recipe["bypassTempC"], "bypassTempC",
                                   40 if bypass_volume else 0, 95 if bypass_volume else 0)
        r = recipe["recipe"]
        grinder_off = isinstance(r, dict) and r.get("grindEnabled") is False
        if grinder_off:
            _exact_keys(r, ("grindEnabled", "grandWater", "pours"), "$.recipe")
            # Match the captured OFF frame, including its first-pour timing byte.
            grind, rpm, command = 0xFE, 60, 8004
        else:
            _exact_keys(r, ("grinderSize", "rpm", "grandWater", "pours"), "$.recipe")
            grind = _integer(r["grinderSize"], "grinderSize", 1, 80)
            rpm = _integer(r["rpm"], "rpm", 60, 120)
            command = 8001
            if rpm % 10:
                raise ProtocolError("rpm must be in 10 RPM steps")
        pours = r["pours"]
        if type(pours) is not list or not 1 <= len(pours) <= 9:
            raise ProtocolError("pours must contain 1..9 entries")
        out = bytearray()
        total = 0
        for index, p in enumerate(pours):
            path = f"$.recipe.pours[{index}]"
            _exact_keys(p, ("volume", "temperature", "flowRate", "pattern", "pausing",
                            "vibBefore", "vibAfter"), path)
            volume = _integer(p["volume"], f"{path}.volume", 1, 500)
            total += volume
            temp = _integer(p["temperature"], f"{path}.temperature", 20, 98)
            if temp not in (20, 98) and not 40 <= temp <= 95:
                raise ProtocolError(f"{path}.temperature must be 40..95 C, RT=20, or BP=98")
            pattern = _integer(p["pattern"], f"{path}.pattern", 0, 2)
            pause = _integer(p["pausing"], f"{path}.pausing", 0, 59)
            flow = p["flowRate"]
            if type(flow) not in (int, float) or flow not in _FLOW_BYTES:
                raise ProtocolError(f"{path}.flowRate must be one of 3.0/3.1/3.2/3.3/3.4/3.5")
            if type(p["vibBefore"]) is not bool or type(p["vibAfter"]) is not bool:
                raise ProtocolError(f"{path}: vibration flags must be booleans")
            vibration = int(p["vibBefore"]) | (int(p["vibAfter"]) << 1)
            while volume > 127:
                out.extend((127, temp, pattern, vibration))
                volume -= 127
            out.extend((volume, temp, pattern, vibration, (-pause) & 255, 0,
                        rpm if index == 0 else 0, _FLOW_BYTES[flow]))
        if _integer(r["grandWater"], "grandWater", 1, 500) != total:
            raise ProtocolError("grandWater must equal sum of pour volumes")
        if total + bypass_volume > 500:
            raise ProtocolError("brew water plus bypass must not exceed 500 ml")
        ratio, remainder = divmod(total * 10, dose)
        if remainder or not 1 <= ratio <= 255:
            raise ProtocolError("ratio cannot be encoded exactly; review recipe instead of rounding")
        # Existing firmware encoding uses float32; reject known rounding mismatch.
        f32 = lambda x: struct.unpack("<f", struct.pack("<f", x))[0]
        if int(f32(f32(f32(ratio) / f32(10)) * f32(dose))) != total:
            raise ProtocolError("firmware ratio arithmetic differs from reviewed water volume")
        if len(out) > 255:
            raise ProtocolError("encoded recipe too long")
        blob = bytes((len(out),)) + bytes(out) + bytes((grind, int(ratio)))
        # Match Yiyi water_brew.flex_build -> legacy build_brew_plan: two
        # float32 values (ml, Celsius), then integer grams. Celsius is passed
        # unchanged; see README for the conflicting external x10 note.
        # Native bypass is configuration, not a fifth through-bed pour.
        dose_frame = _command(8102, struct.pack("<ffi", bypass_volume, bypass_temp, dose))
        return [("bypass+dose" if bypass_volume else "dose", dose_frame),
                ("cup", _command(8104, struct.pack("<ff", 110.0, 90.0))),
                ("recipe_no_grind" if grinder_off else "recipe", _command(command, blob))]
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ProtocolError(f"invalid recipe shape: {exc}") from exc
