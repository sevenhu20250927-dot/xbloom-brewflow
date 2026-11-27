"""Offline codec tests. Notifications below are synthetic, NOT machine captures."""
import copy
import math
import struct
import unittest

from xbloom_bridge.protocol import (
    FrameAssembler, ProtocolError, build_recipe_frames, cancel_frame, crc16,
    decode_frame, handshake_frame, start_frame, status_query_frame,
)


def synthetic_notification(ftype, payload=b"", subtype=0x9e, marker=0xc1):
    raw = b"\x58\x02\x07" + bytes((ftype, subtype)) + struct.pack("<I", 12 + len(payload)) + bytes((marker,)) + payload
    return raw + struct.pack("<H", crc16(raw))


def reviewed_recipe():
    return {"cupType": "xdripper", "doseGrams": 15, "recipe": {"grinderSize": 51, "rpm": 110,
            "grandWater": 240, "pours": [
        {"volume": 45, "temperature": 94, "flowRate": 3.0, "pattern": 2,
         "pausing": 20, "vibBefore": False, "vibAfter": True},
        {"volume": 105, "temperature": 94, "flowRate": 3.5, "pattern": 2,
         "pausing": 8, "vibBefore": False, "vibAfter": False},
        {"volume": 90, "temperature": 94, "flowRate": 3.5, "pattern": 1,
         "pausing": 0, "vibBefore": False, "vibAfter": False},
    ]}}


class FrameTests(unittest.TestCase):
    def test_crc_known_check_value(self):
        self.assertEqual(crc16(b"123456789"), 0x2189)

    def test_handshake_matches_upstream_published_capture(self):
        # Literal capture declared in installed skill 1.3.2, not recaptured here.
        self.assertEqual(handshake_frame().hex(), "580101a41f1400000001b900000001000000bdd1")

    def test_split_at_every_boundary_and_multiple_frames(self):
        frame = synthetic_notification(0x57, b"\x22")
        for split in range(1, len(frame)):
            asm = FrameAssembler()
            self.assertEqual(asm.feed(frame[:split]), [])
            self.assertEqual(asm.feed(frame[split:] + frame), [frame, frame])
            self.assertEqual(asm.buffer, b"")

    def test_split_header_and_garbage_resynchronization(self):
        frame = synthetic_notification(0x57, b"\x01")
        asm = FrameAssembler()
        self.assertEqual(asm.feed(b"garbage" + frame[:2]), [])
        self.assertEqual(asm.feed(frame[2:]), [frame])
        self.assertEqual(asm.discarded_bytes, 7)

    def test_invalid_and_plausible_corrupt_length_recovery(self):
        frame = synthetic_notification(0x57, b"\x01")
        for n in (0, 11, 4097, 2048):
            asm = FrameAssembler()
            corrupt = b"\x58\x02\x07\x49\x9e" + struct.pack("<I", n) + b"junk"
            self.assertEqual(asm.feed(corrupt + frame), [frame])
            self.assertLess(len(asm.buffer), 4096)

    def test_bad_crc_is_preserved_by_assembler_then_rejected(self):
        frame = bytearray(synthetic_notification(0x57, b"\x01"))
        frame[-1] ^= 1
        self.assertEqual(FrameAssembler().feed(frame), [bytes(frame)])
        with self.assertRaisesRegex(ProtocolError, "CRC"):
            decode_frame(frame)

    def test_corrupt_length_does_not_swallow_following_frame(self):
        good = synthetic_notification(0x57,b"\x01")
        bad = bytearray(synthetic_notification(0x57,b"\x22"))
        bad[5:9] = struct.pack("<I",len(bad)+len(good))
        asm = FrameAssembler()
        frames = asm.feed(bad+good)
        self.assertEqual(frames[-1],good)
        self.assertEqual(decode_frame(frames[-1])["state"],"idle")
        self.assertEqual(asm.buffer,b"")

    def test_truncation_length_and_header_rejected(self):
        frame = synthetic_notification(0x57, b"\x01")
        for value in (frame[:5], frame[:-1], frame + b"\0", b"\x58\x01\x01" + frame[3:]):
            with self.assertRaises(ProtocolError):
                decode_frame(value)

    def test_unknown_and_unknown_marker_remain_observations(self):
        ev = decode_frame(synthetic_notification(0x77, b"\x40\x00\x00"))
        self.assertEqual(ev["kind"], "echo_or_unknown")
        self.assertEqual(ev["payload_hex"], "400000")
        self.assertNotIn("refusal", ev)
        self.assertNotIn("accepted", ev)
        ev = decode_frame(synthetic_notification(0x57, b"\x24", marker=0xc2))
        self.assertNotIn("state", ev)

    def test_all_known_states_and_unknown_state(self):
        for code, state in ((1,"idle"),(12,"no_water"),(15,"no_beans"),(16,"brewing"),
                            (29,"loading"),(30,"awaiting_confirm"),(31,"armed"),
                            (34,"starting"),(35,"brewing"),(36,"ready"),(59,"brewing"),
                            (65,"complete"),(255,"unknown_0xff")):
            ev = decode_frame(synthetic_notification(0x57, bytes((code,))))
            self.assertEqual(ev["state"], state)
            self.assertNotIn("completed", ev)

    def test_done_is_only_candidate(self):
        ev = decode_frame(synthetic_notification(0x40))
        self.assertEqual(ev["kind"], "completion_candidate")
        self.assertTrue(ev["completion_candidate"])

    def test_legacy_grind_is_provisional(self):
        ev = decode_frame(synthetic_notification(0x3a))
        self.assertEqual(ev["event_name"],"grinding_report")
        self.assertEqual(ev["interpretation"],"upstream_provisional")

    def test_water_coffee_units_and_invalid_readings(self):
        for ftype, value, field, expected in ((0x4b,240000,"water_g",240),(0x15,210,"coffee_g",210)):
            ev = decode_frame(synthetic_notification(ftype,struct.pack("<f",value)))
            self.assertEqual(ev[field],expected)
        for value in (-1,math.nan,math.inf,2001):
            ev = decode_frame(synthetic_notification(0x15,struct.pack("<f",value)))
            self.assertIsNone(ev["coffee_g"])
            self.assertIn("reading_error",ev)
        ev = decode_frame(synthetic_notification(0x15,b"\0"))
        self.assertEqual(ev["reading_error"],"truncated_float32")

    def test_machine_info_retains_reported_grind_and_unknown_mode(self):
        payload = bytearray(55)
        payload[:13] = b"J15B01C68E160 "
        payload[19:29] = b"V12.0D.500"
        payload[33],payload[36],payload[37] = 0,1,85
        payload[51:55] = bytes.fromhex("01020304")
        ev = decode_frame(synthetic_notification(0x49,payload))
        self.assertEqual(ev["grind_reported"],55)
        self.assertEqual(ev["grind_raw"],85)
        self.assertEqual(ev["mode"],"unknown")
        self.assertEqual(ev["water_source"],"plumbed")
        self.assertNotIn("water_ok",ev)
        self.assertEqual(ev["firmware"],"V12.0D.500")


class RecipeTests(unittest.TestCase):
    def test_reviewed_recipe_matches_frozen_old_encoder_output(self):
        # Protocol regression fixture shared with the published CLI.
        # was read and passed unchanged to skill 1.3.2 build_brew_plan on 2026-11-05.
        # These are encoder parity vectors, NOT captured device acceptance evidence.
        expected = [
            "580101a61f180000000100000000000000000f00000050fd",
            "580101a81f14000000010000dc420000b44221a1",
            "580101411f2700000001182d5e0202ec006e1e695e0200f80000235a5e01000000002333a0db9b",
        ]
        self.assertEqual([raw.hex() for _,raw in build_recipe_frames(reviewed_recipe())],expected)

    def test_load_frames_exclude_actions_and_preserve_reviewed_fields(self):
        recipe = reviewed_recipe()
        original = copy.deepcopy(recipe)
        frames = build_recipe_frames(recipe)
        self.assertEqual([name for name,_ in frames],["dose","cup","recipe"])
        self.assertEqual([int.from_bytes(raw[3:5],"little") for _,raw in frames],[8102,8104,8001])
        blob = frames[-1][1][10:-2]
        self.assertEqual(blob[-2:], bytes((51,160)))
        self.assertEqual(list(blob[1:9]),[45,94,2,2,236,0,110,30])
        self.assertEqual(recipe,original)
        for _,raw in frames:
            self.assertEqual(len(raw),int.from_bytes(raw[5:9],"little"))
            self.assertEqual(crc16(raw[:-2]),int.from_bytes(raw[-2:],"little"))

    def test_start_cancel_query_are_separate(self):
        self.assertEqual(int.from_bytes(start_frame()[3:5],"little"),8002)
        self.assertEqual(int.from_bytes(cancel_frame()[3:5],"little"),0x9e47)
        self.assertEqual(status_query_frame().hex(),"580101561f0c00000001c015")

    def test_invalid_recipe_fails_without_normalization(self):
        edits = [lambda r:r.update(doseGrams=True),
                 lambda r:r.update(cupType="other"),
                 lambda r:r["recipe"].update(grinderSize=0),
                 lambda r:r["recipe"].update(grinderSize=81),
                 lambda r:r["recipe"].update(rpm=101),
                 lambda r:r["recipe"].update(grandWater=241),
                 lambda r:r["recipe"]["pours"][0].update(temperature=96),
                 lambda r:r["recipe"]["pours"][0].update(volume=45.5),
                 lambda r:r["recipe"]["pours"][0].update(flowRate=3.05),
                 lambda r:r["recipe"]["pours"][0].update(vibAfter="false")]
        for edit in edits:
            recipe=reviewed_recipe()
            edit(recipe)
            with self.assertRaises(ProtocolError):
                build_recipe_frames(recipe)

    def test_unrepresentable_ratio_rejected_not_adjusted(self):
        recipe=reviewed_recipe()
        recipe["recipe"]["pours"][2]["volume"]=91
        recipe["recipe"]["grandWater"]=241
        with self.assertRaisesRegex(ProtocolError,"ratio"):
            build_recipe_frames(recipe)


if __name__ == "__main__":
    unittest.main()
