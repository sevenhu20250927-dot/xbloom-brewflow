"""Synthetic transport/evidence tests; these never import bleak or use hardware."""
import asyncio
import json
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from xbloom_bridge import protocol as p
from xbloom_bridge.recording import Journal, read_events, recipe_digest, summarize
from xbloom_bridge.transport import BridgeError, DeviceLock, Session
from xbloom_bridge.__main__ import parser, replay, run


def notification(code, payload=b"", marker=0xc1):
    body = b"\x58\x02\x07" + struct.pack("<HI", code, 12 + len(payload))
    body += bytes([marker]) + payload
    return body + struct.pack("<H", p.crc16(body))


def state(value):
    return notification(0x9e57, bytes([value]))


def machine_info(mode=b"\0\0\0\0"):
    payload = bytearray(55)
    payload[:13] = b"SYNTHETIC0001"
    payload[19:29] = b"V12.0D.500"
    payload[33] = 1
    payload[37] = 81
    payload[51:55] = mode
    return notification(0x9e49, payload)


def synthetic_recipe():
    return {"cupType": "xdripper", "doseGrams": 15, "recipe": {
        "grinderSize": 51, "rpm": 110, "grandWater": 240,
        "pours": [{"volume": volume, "temperature": 94, "flowRate": 3.5,
                   "pattern": 2, "pausing": 0, "vibBefore": False,
                   "vibAfter": False} for volume in (45, 105, 90)]}}


class FakeClient:
    """In-memory fake, not a claim about machine timing or semantics."""
    def __init__(self, address, disconnected_callback, timeout):
        self.address = address
        self.disconnected_callback = disconnected_callback
        self.is_connected = False
        self.services = []
        self.callback = None
        self.writes = []
        self.on_write = None
        self.read_values = {}
        self.reads = []

    async def connect(self):
        self.is_connected = True

    async def disconnect(self):
        self.is_connected = False
        self.disconnected_callback(self)

    async def start_notify(self, characteristic, callback):
        self.callback = callback
        self.characteristic = characteristic

    def emit(self, raw):
        self.callback(p.CHAR_STATUS, raw)

    async def write_gatt_char(self, characteristic, data, response):
        self.writes.append((characteristic, bytes(data), response))
        if self.on_write:
            self.on_write(bytes(data))

    async def read_gatt_char(self, characteristic):
        self.reads.append(characteristic)
        result = self.read_values[characteristic]
        if isinstance(result, Exception):
            raise result
        return result


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.journal = Journal(self.temp.name, operation="synthetic_test")
        self.session = Session("synthetic-" + uuid.uuid4().hex, self.journal,
                               client_factory=FakeClient)
        await self.session.__aenter__()
        self.client = self.session.client

    async def asyncTearDown(self):
        await self.session.close()
        self.journal.close()
        self.temp.cleanup()

    def records(self):
        return list(read_events(self.journal.path))

    def arm(self):
        self.session.loaded_digest = "synthetic-reviewed-digest"
        self.client.emit(state(0x1f))

    async def test_handshake_records_unrelated_and_fragmented_notifications(self):
        def reply(packet):
            self.assertEqual(packet, p.handshake_frame())
            # Intent must already be durable when the fake receives the write.
            self.assertEqual(self.records()[-1]["kind"], "tx_intent")
            raw = notification(0x9eee, b"opaque") + machine_info()
            self.client.emit(raw[:7])
            self.client.emit(raw[7:])
        self.client.on_write = reply
        result = await self.session.handshake(timeout=.05)
        self.assertEqual(result["data"]["firmware"], "V12.0D.500")
        self.assertEqual(len(self.client.writes), 1)
        self.assertIs(self.client.writes[0][2], False)
        self.assertEqual([e["data"]["kind"] for e in self.records()
                          if e["kind"] == "decoded"],
                         ["echo_or_unknown", "machine_info"])
        self.assertEqual(sum(e["kind"] == "rx" for e in self.records()), 2)

    async def test_observe_sends_no_commands_and_keeps_idle_data(self):
        self.client.emit(state(1))
        self.client.emit(notification(0x9e15, struct.pack("<f", 0)))
        await self.session.observe(.001)
        self.assertEqual(self.client.writes, [])
        self.assertEqual(len(self.session.events), 2)

    async def test_brew_finishes_on_buffered_program_end_without_extra_write(self):
        self.client.emit(notification(40512, b''))
        self.arm()
        self.client.on_write = lambda _: self.client.emit(state(0x22))
        await self.session.start("synthetic-reviewed-digest", authorized=True, timeout=.05)
        self.client.emit(notification(40510, bytes(4)))
        self.client.emit(notification(40511, b''))
        self.assertIsNone(self.session.brew_window.reason)
        self.client.emit(notification(40512, b'') + notification(0x9e15, struct.pack("<f", 999)))
        self.assertEqual(await asyncio.wait_for(self.session.observe_brew(), 1), "program_end")
        self.assertEqual(len(self.client.writes), 1)
        self.assertEqual(summarize(self.journal.path)["coffee_curve"], [])

    async def test_no_notifications_wakes_observer_without_a_terminal_packet(self):
        self.arm()
        self.client.on_write = lambda _: self.client.emit(state(0x22))
        await self.session.start("synthetic-reviewed-digest", authorized=True, timeout=.05)
        self.assertEqual(self.session.brew_window.idle_seconds, 30)
        self.session.brew_window.idle_seconds = .02
        self.assertEqual(await asyncio.wait_for(self.session.observe_brew(), 1), "no_update")
        self.assertEqual(len(self.client.writes), 1)

    async def test_explicit_brew_cap_remains_available(self):
        self.arm()
        self.client.on_write = lambda _: self.client.emit(state(0x22))
        await self.session.start("synthetic-reviewed-digest", authorized=True, timeout=.05)
        self.assertEqual(await self.session.observe_brew(.01), "time_limit")

    async def test_corrupt_frame_is_evidence_not_a_state(self):
        raw = bytearray(state(0x24))
        raw[-1] ^= 1
        self.client.emit(raw)
        self.assertEqual(self.session.events, [])
        rows = self.records()
        self.assertEqual([e["kind"] for e in rows[-2:]], ["rx", "decode_error"])
        self.assertEqual(rows[-2]["raw_hex"], bytes(raw).hex())
        self.client.emit(state(1))
        self.assertEqual(self.session.events[-1]["data"]["state"], "idle")

    async def test_log_failure_before_write_blocks_command(self):
        with patch.object(self.journal, "append", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                await self.session.handshake(timeout=.001)
        self.assertEqual(self.client.writes, [])

    async def test_failed_write_is_uncertain_and_never_retried(self):
        def fail(_):
            raise OSError("link dropped after transmit")
        self.client.on_write = fail
        with self.assertRaises(OSError):
            await self.session.handshake(timeout=.001)
        self.client.on_write = None
        with self.assertRaises(BridgeError):
            await self.session.handshake(timeout=.001)
        self.assertEqual(len(self.client.writes), 1)
        self.assertTrue(any(e["kind"] == "write_uncertain" for e in self.records()))

    async def test_postwrite_log_failure_latches_uncertainty(self):
        append = self.journal.append

        def fail_postwrite(kind, **data):
            if kind == "tx_returned":
                raise OSError("disk full after write")
            return append(kind, **data)

        with patch.object(self.journal, "append", side_effect=fail_postwrite):
            with self.assertRaises(OSError):
                await self.session.handshake(timeout=.001)
        # Storage recovering must not make the earlier write outcome certain.
        with self.assertRaises(BridgeError):
            await self.session.handshake(timeout=.001)
        self.assertEqual(len(self.client.writes), 1)

    async def test_start_requires_authority_and_matching_recipe(self):
        self.arm()
        for digest, authorized in [("synthetic-reviewed-digest", False), ("other", True)]:
            with self.assertRaises(BridgeError):
                await self.session.start(digest, authorized=authorized, timeout=.001)
        self.assertEqual(self.client.writes, [])

    async def test_start_without_evidence_never_sends_fallback_or_duplicate(self):
        self.arm()
        with self.assertRaises(BridgeError):
            await self.session.start("synthetic-reviewed-digest", authorized=True, timeout=.001)
        self.client.emit(state(0x1f))
        with self.assertRaises(BridgeError):
            await self.session.start("synthetic-reviewed-digest", authorized=True, timeout=.001)
        self.assertEqual([w[1] for w in self.client.writes], [p.start_frame()])
        self.assertTrue(any(e["kind"] == "start_unconfirmed" for e in self.records()))
        self.assertFalse(any(e["kind"] == "start_observed" for e in self.records()))

    async def test_start_observed_still_does_not_mean_completed(self):
        self.arm()
        self.client.on_write = lambda _: self.client.emit(state(0x22))
        await self.session.start("synthetic-reviewed-digest", authorized=True, timeout=.05)
        self.client.emit(state(0x24))
        self.client.emit(state(1))
        summary = summarize(self.journal.path)
        self.assertEqual(summary["completion"], "unconfirmed")
        self.assertIsNone(summary["machine_brew_duration_s"])

    async def test_unexpected_disconnect_invalidates_staged_recipe(self):
        self.arm()
        await self.client.disconnect()
        self.assertIsNone(self.session.loaded_digest)
        with self.assertRaises(BridgeError):
            await self.session.start("synthetic-reviewed-digest", authorized=True, timeout=.001)
        self.assertEqual(self.client.writes, [])
        self.assertTrue(summarize(self.journal.path)["interruptions"])

    async def test_read_only_handshake_timeout_does_not_retry(self):
        with self.assertRaises(BridgeError):
            await self.session.handshake(timeout=.001)
        self.assertEqual([w[1] for w in self.client.writes], [p.handshake_frame()])

    async def test_rx_record_failure_prevents_subsequent_writes(self):
        with patch.object(self.journal, "append", side_effect=OSError("disk full")):
            self.client.emit(state(1))
        with self.assertRaises(BridgeError):
            await self.session.handshake(timeout=.001)
        self.assertEqual(self.client.writes, [])

    async def test_cancel_needs_explicit_authorization(self):
        with self.assertRaises(BridgeError):
            await self.session.cancel(timeout=.001)
        self.assertEqual(self.client.writes, [])

    async def test_rinse_sends_only_reviewed_grinder_off_pour(self):
        recipe = p.rinse_recipe(50)
        with self.assertRaises(p.ProtocolError):
            p.build_recipe_frames(recipe)
        with self.assertRaises(p.ProtocolError):
            p.rinse_recipe(50.5)
        self.client.emit(state(1))
        def reply(packet):
            if int.from_bytes(packet[3:5], 'little') == 8004:
                self.client.emit(state(0x1f))
            elif packet == p.start_frame():
                self.client.emit(state(0x22))
        self.client.on_write = reply
        await self.session.load(recipe, rinse=True)
        packets = [entry[1] for entry in self.client.writes]
        self.assertEqual([int.from_bytes(raw[3:5], 'little') for raw in packets], [8102, 8104, 8004])
        self.assertEqual(packets[-1][11:15], bytes([50, 92, 2, 0]))
        self.assertEqual(packets[-1][-4], 0xFE)
        await self.session.start(recipe_digest(recipe), authorized=True)
        self.assertEqual(self.client.writes[-1][1], p.start_frame())

    async def test_load_snapshots_recipe_and_never_navigates_or_starts(self):
        self.client.emit(machine_info())
        self.client.emit(state(1))
        recipe = synthetic_recipe()
        expected = p.build_recipe_frames(recipe)

        def reply(packet):
            if packet == expected[-1][1]:
                self.client.emit(state(0x1f))
        self.client.on_write = reply
        await self.session.load(recipe, timeout=.05)
        self.assertEqual([row[1] for row in self.client.writes],
                         [frame for _, frame in expected])
        self.assertEqual(self.session.loaded_digest, recipe_digest(recipe))
        recipe["recipe"]["grinderSize"] = 55
        snapshots = [e for e in self.records() if e["kind"] == "recipe_snapshot"]
        self.assertEqual(snapshots[0]["recipe"]["recipe"]["grinderSize"], 51)
        self.assertEqual(snapshots[0]["sha256"], self.session.loaded_digest)

    async def test_load_with_unobserved_idle_times_out_without_writes(self):
        with self.assertRaises(BridgeError):
            await self.session.load(synthetic_recipe(), timeout=.001)
        self.assertEqual(self.client.writes, [])

    async def test_bypass_load_records_native_parameters_without_starting(self):
        recipe = synthetic_recipe()
        recipe.update(bypassMl=10, bypassTempC=90)
        self.client.emit(state(1))

        def reply(packet):
            if int.from_bytes(packet[3:5], 'little') == 8001:
                self.client.emit(state(0x1f))
        self.client.on_write = reply
        await self.session.load(recipe, timeout=.05)
        packets = [row[1] for row in self.client.writes]
        self.assertEqual([int.from_bytes(raw[3:5], 'little') for raw in packets], [8102, 8104, 8001])
        self.assertEqual(packets[0].hex(), '580101a61f1800000001000020410000b4420f0000000fff')
        snapshots = [r for r in self.records() if r['kind'] == 'recipe_snapshot']
        self.assertEqual(snapshots[0]['recipe']['bypassMl'], 10)
        self.assertEqual(snapshots[0]['recipe']['bypassTempC'], 90)
        recipe['bypassMl'] = 11
        with self.assertRaises(BridgeError):
            await self.session.start(recipe_digest(recipe), authorized=True, timeout=.001)
        self.assertEqual(len(self.client.writes), 3)
        self.assertFalse(self.session.start_attempted)

    async def test_load_in_brewing_or_no_water_state_sends_nothing(self):
        self.client.emit(machine_info())
        for code in (0x10, 0x0c):
            self.client.emit(state(code))
            with self.assertRaises(BridgeError):
                await self.session.load(synthetic_recipe(), timeout=.001)
        self.assertEqual(self.client.writes, [])

    async def test_unknown_mode_with_idle_can_load_when_machine_reports_armed(self):
        self.client.emit(machine_info(mode=b"\xff" * 4))
        self.assertEqual(self.session.events[-1]["data"]["mode"], "unknown")
        self.client.emit(state(1))
        recipe = synthetic_recipe()
        frames = p.build_recipe_frames(recipe)
        self.client.on_write = lambda packet: self.client.emit(state(0x1f)) if packet == frames[-1][1] else None
        await self.session.load(recipe, timeout=.05)
        self.assertEqual(self.session.loaded_digest, recipe_digest(recipe))
        self.assertEqual([w[1] for w in self.client.writes], [frame for _, frame in frames])
        observations = [r for r in self.records() if r["kind"] == "load_mode_observation"]
        self.assertEqual(observations[-1]["mode"], "unknown")

    async def test_unconfirmed_load_is_not_repeated(self):
        self.client.emit(state(1))
        with self.assertRaises(BridgeError):
            await self.session.load(synthetic_recipe(), timeout=.001)
        written = list(self.client.writes)
        self.assertEqual(len(written), 3)
        with self.assertRaises(BridgeError):
            await self.session.load(synthetic_recipe(), timeout=.001)
        self.assertEqual(self.client.writes, written)

    async def test_device_information_reads_only_advertised_readable_standard_fields(self):
        uuid_for = lambda short: f"0000{short}-0000-1000-8000-00805f9b34fb"
        make_char = lambda short, properties: SimpleNamespace(uuid=uuid_for(short), properties=properties)
        self.client.services = [SimpleNamespace(uuid=uuid_for("180a"), characteristics=[
            make_char("2a26", ["read"]), make_char("2a25", ["read"]),
            make_char("2a29", ["notify"]), make_char("ffff", ["read"])]),
            SimpleNamespace(uuid=uuid_for("180f"), characteristics=[make_char("2a24", ["read"])])]
        self.client.read_values = {uuid_for("2a26"): b"V12.0D.500\0", uuid_for("2a25"): b"SYNTHETIC\xff"}
        await self.session.read_device_information()
        self.assertEqual(self.client.reads, [uuid_for("2a26"), uuid_for("2a25")])
        self.assertEqual(self.client.writes, [])
        rows = [e for e in self.records() if e["kind"] == "device_information"]
        self.assertEqual(rows[0]["text"], "V12.0D.500")
        self.assertEqual(rows[1]["raw_hex"], b"SYNTHETIC\xff".hex())
        self.assertEqual(summarize(self.journal.path)["device_information"]["firmware_revision"],
                         "V12.0D.500")

    async def test_device_information_read_failure_is_logged_and_next_field_retained(self):
        fw = "00002a26-0000-1000-8000-00805f9b34fb"
        serial = "00002a25-0000-1000-8000-00805f9b34fb"
        self.client.services = [SimpleNamespace(uuid="0000180a-0000-1000-8000-00805f9b34fb",
            characteristics=[SimpleNamespace(uuid=u, properties=["read"]) for u in (fw, serial)])]
        self.client.read_values = {fw: OSError("unavailable"), serial: b"SYNTHETIC"}
        await self.session.read_device_information()
        self.assertEqual(self.client.reads, [fw, serial])
        self.assertEqual(self.client.writes, [])
        self.assertTrue(any(e["kind"] == "gatt_read_error" for e in self.records()))
        self.assertEqual(summarize(self.journal.path)["device_information"], {"serial": "SYNTHETIC"})


class CLIAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_brew_rejected_before_journal_or_hardware_without_matching_authority(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "synthetic.json"
            recipe = synthetic_recipe()
            path.write_text(json.dumps(recipe))
            base = ["brew", "--address", "synthetic", "--recipe", str(path), "--reviewed-sha256"]
            commands = [base + [recipe_digest(recipe)], base + ["wrong", "--confirm-start"]]
            with patch("xbloom_bridge.__main__.Journal", side_effect=AssertionError("must not open log")), \
                 patch("xbloom_bridge.__main__.Session", side_effect=AssertionError("must not connect")):
                for command in commands:
                    with self.assertRaises(BridgeError):
                        await run(parser().parse_args(command))

    async def test_cancel_rejected_before_journal_or_hardware_without_authority(self):
        with patch("xbloom_bridge.__main__.Journal", side_effect=AssertionError("must not open log")), \
             patch("xbloom_bridge.__main__.Session", side_effect=AssertionError("must not connect")):
            with self.assertRaises(BridgeError):
                await run(parser().parse_args(["cancel", "--address", "synthetic"]))


class EvidenceTests(unittest.TestCase):
    def test_summary_uses_receive_timestamp_for_samples_and_states(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "synthetic.jsonl"
            rows = [{"kind": "decoded", "elapsed_s": 20, "received_elapsed_s": 12,
                     "received_wall_utc": "synthetic-arrival", "seq": 1,
                     "data": {"kind": "weight", "coffee_g": 140}},
                    {"kind": "decoded", "elapsed_s": 25, "received_elapsed_s": 13,
                     "received_wall_utc": "synthetic-arrival2", "seq": 2,
                     "data": {"kind": "state", "state": "ready"}}]
            path.write_text("".join(json.dumps(row) + "\n" for row in rows))
            result = summarize(path)
            self.assertEqual(result["coffee_curve"], [[12, 140]])
            self.assertEqual(result["state_history"][0]["elapsed_s"], 13)
            self.assertEqual(result["state_history"][0]["wall_utc"], "synthetic-arrival2")
            self.assertEqual(result["completion_candidates"][0]["elapsed_s"], 13)

    def test_expected_disconnect_is_not_reported_as_interruption(self):
        with tempfile.TemporaryDirectory() as temp:
            journal = Journal(temp, operation="synthetic_disconnect")
            journal.append("disconnected", expected=True)
            self.assertEqual(summarize(journal.path)["interruptions"], [])
            journal.append("disconnected", expected=False)
            journal.close()
            self.assertEqual(len(summarize(journal.path)["interruptions"]), 1)

    def test_replay_reports_unassembled_tail_and_discarded_noise(self):
        with tempfile.TemporaryDirectory() as temp:
            journal = Journal(temp, operation="synthetic_replay")
            journal.append("rx", raw_hex=(b"junk" + state(1) + state(0x24)[:8]).hex())
            journal.close()
            result = replay(journal.path)
            self.assertEqual(result["frames"], 1)
            self.assertEqual(result["states"], ["idle"])
            self.assertEqual(result["trailing_bytes"], 8)
            self.assertEqual(result["discarded_bytes"], 4)

    def test_lock_excludes_second_owner_and_releases(self):
        address = "synthetic-" + uuid.uuid4().hex
        first, second = DeviceLock(address), DeviceLock(address)
        try:
            first.acquire()
            with self.assertRaises(BridgeError):
                second.acquire()
            first.close()
            second.acquire()
        finally:
            first.close()
            second.close()
            first.path.unlink(missing_ok=True)

    def test_trailing_damaged_record_preserves_prior_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            journal = Journal(temp, operation="synthetic_recovery")
            journal.append("decoded", data={"kind": "state", "state": "ready"})
            journal.append("decoded", data={"kind": "weight", "coffee_g": 200.0})
            journal.close()
            with journal.path.open("a") as stream:
                stream.write('{"kind":"rx","raw_hex":')
            result = summarize(journal.path)
            self.assertEqual(result["completion"], "unconfirmed")
            self.assertEqual(result["event_counts"]["journal_damage"], 1)
            self.assertEqual(result["coffee_curve"][0][1], 200)
            self.assertEqual(result["states_observed"], {"ready": 1})
            self.assertIsNone(result["machine_brew_duration_s"])
            self.assertIn("NOT machine brew timer", result["clock_definition"])

    def test_recipe_snapshot_and_hash_are_recoverable(self):
        recipe = {"doseGrams": 15, "recipe": {"grinderSize": 51}}
        with tempfile.TemporaryDirectory() as temp:
            journal = Journal(temp, operation="synthetic_recipe", recipe=recipe)
            journal.close()
            recipe["recipe"]["grinderSize"] = 55
            result = summarize(journal.path)["session"]
            self.assertEqual(result["recipe"]["recipe"]["grinderSize"], 51)
            self.assertEqual(result["recipe_sha256"], recipe_digest(result["recipe"]))


if __name__ == "__main__":
    unittest.main()
