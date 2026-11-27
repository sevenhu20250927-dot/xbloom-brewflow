import unittest

from coffee_product.live_brew import LiveBrew


class LiveSamples(unittest.TestCase):
    def setUp(self):
        self.brew = LiveBrew()
        self.brew.accept({"kind": "session", "recipe": {
            "recipe": {"pours": [{"volume": 20}, {"volume": 25}]}, "bypassMl": 10}})

    def send(self, t, kind="weight", **data):
        self.brew.accept({"kind": "decoded", "received_elapsed_s": t, "data": {"kind": kind, **data}})

    def stage(self, t, i):
        self.send(t, "legacy_event", code=40510, payload_hex=(i-1).to_bytes(4, "little").hex())

    def start(self):
        self.brew.accept({"kind": "tx_intent", "label": "start_commit"})

    def test_start_and_stages_follow_device(self):
        self.stage(0, 1)
        self.send(1, water_g=140)
        self.start()
        self.send(2, water_g=140)
        self.assertIsNone(self.brew.snapshot()["elapsed_s"])
        self.stage(3, 1)
        self.send(3.2, water_g=2)
        self.assertIsNone(self.brew.snapshot()["stage_ml"])
        self.send(11.5, water_g=20)
        self.stage(12, 2)
        self.stage(12.2, 2)
        self.send(13.1, water_g=23)
        self.send(11, water_g=0)
        self.assertEqual(self.brew.snapshot()["stages"], [[0, 1], [9, 2]])
        self.assertEqual(self.brew.snapshot()["stage_ml"], 3)
        self.assertTrue(self.brew.snapshot()["flowing"])

    def test_pairing_and_bypass(self):
        self.start()
        self.stage(10, 1)
        self.send(10.1, water_g=10)
        self.send(10.8, coffee_g=3)
        self.send(11.1, water_g=20)
        self.send(12.1, coffee_g=12)
        self.send(14.1, water_g=44)
        self.send(14.2, coffee_g=35)
        self.send(15.1, water_g=45)
        self.send(15.2, coffee_g=36)
        self.assertEqual(self.brew.snapshot()["points"], [
            [0, 10, 3, 7], [1, 20, None, None], [2, None, 12, None],
            [4, 44, 35, 9], [5, 45, 36, None]])

    def test_counter_reset_and_idle(self):
        self.start()
        self.stage(2, 1)
        self.send(3, water_g=20)
        self.send(3.2, coffee_g=14)
        self.send(3.5, water_g=0)
        self.send(4, coffee_g=16)
        self.send(5, "state", state="idle")
        self.send(6, coffee_g=134)
        self.stage(7, 1)
        result = self.brew.snapshot()
        self.assertEqual(result["points"], [[1, 20, 14, None], [2, None, 16, None]])
        self.assertTrue(result["counter_reset"] and result["closed"])
        self.assertFalse(result["flowing"])

    def test_no_telemetry_from_prestart_failure(self):
        self.brew.accept({"kind": "error", "error": "handshake timeout"})
        self.stage(1, 1)
        result = self.brew.snapshot()
        self.assertIsNone(result["elapsed_s"])
        self.assertEqual(result["points"], [])

    def test_end_freezes_points_clock_and_flow_in_receive_order(self):
        self.start()
        self.send(1, "completion_candidate", code=40512)
        self.stage(2, 1)
        self.send(3, "echo_or_unknown", code=40512)
        self.send(4, "legacy_event", code=40511)
        self.send(7, coffee_g=120)
        self.send(8, "completion_candidate", code=40512)
        frozen = self.brew.snapshot()
        self.send(8, coffee_g=999)
        self.send(9, coffee_g=0)
        self.send(10, "state", state="idle")
        self.assertEqual(frozen, self.brew.snapshot())
        self.assertEqual((frozen["elapsed_s"], frozen["stop_reason"], frozen["points"][-1][2]),
                         (6, "program_end", 120))

    def test_progress_renews_deadline_but_a_flat_or_falling_scale_does_not(self):
        self.start()
        self.stage(1, 1)
        self.send(2, coffee_g=50)
        self.send(30, coffee_g=51)
        self.send(59.9, coffee_g=51)
        self.assertFalse(self.brew.closed)
        self.send(60, coffee_g=0)
        self.send(61, coffee_g=999)
        self.assertEqual(self.brew.snapshot()["stop_reason"], "no_update")
        self.assertEqual(self.brew.points[-1][2], 51)

    def test_programmed_bloom_and_grinding_keep_live_scale_but_not_a_dead_link(self):
        self.brew.accept({"kind":"session", "recipe":{"recipe":{"pours":[
            {"volume":45, "flowRate":3, "pausing":50}]}}})
        self.start()
        self.send(1, "legacy_event", code=40506)
        for t in (10, 25, 38):
            self.send(t, coffee_g=0)
        self.stage(39, 1)
        for t in (40, 60, 80, 100):
            self.send(t, coffee_g=2)
        self.assertFalse(self.brew.closed)
        self.brew.window.expire(129.9)
        self.assertIsNone(self.brew.window.reason)
        self.brew.window.expire(130)
        self.assertEqual(self.brew.window.reason, "no_update")

    def test_progress_after_five_minutes_and_tail_drainage_are_kept(self):
        self.start()
        self.stage(0, 1)
        self.send(2, "legacy_event", code=40511)
        for t in range(5, 366, 20):
            self.send(t, coffee_g=t / 2)
        self.assertFalse(self.brew.closed)
        self.send(370, "completion_candidate", code=40512)
        self.assertEqual(self.brew.snapshot()["elapsed_s"], 370)

    def test_stalled_grinder_scale_heartbeats_cannot_hold_capture_forever(self):
        self.start()
        self.send(1, "legacy_event", code=40506)
        for t in range(2, 62):
            self.send(t, coffee_g=0)
        self.assertEqual(self.brew.window.ended_at, 61)
        self.assertEqual(self.brew.window.reason, "no_update")
