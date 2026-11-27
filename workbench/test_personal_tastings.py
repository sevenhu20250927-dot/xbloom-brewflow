import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import schema
from coffeeSys import CoffeeInventoryHandler
from operations import delete_brew_record


class PersonalTastingFlow(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        db = patch.object(schema, "DB_PATH", Path(temp.name) / "temporary.db")
        db.start()
        self.addCleanup(db.stop)
        schema.init_db()
        with schema.get_db_connection() as conn:
            conn.execute("""INSERT INTO brew_records(bean_id,brew_date,data_json,created_at,updated_at)
                            VALUES(1,'2026-11-06','{}','','')""")
        server = ThreadingHTTPServer(("127.0.0.1", 0), CoffeeInventoryHandler)
        self.port = server.server_port
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

    def request(self, path, data=None):
        client = HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            client.request("GET" if data is None else "POST", "/api/tastings" + path,
                           None if data is None else json.dumps(data),
                           {"Content-Type": "application/json"})
            response = client.getresponse()
            return response.status, json.load(response)
        finally:
            client.close()

    def test_two_drinkers_one_cup_and_concurrent_edit(self):
        people = [self.request("/people", {"name": name})[1]["id"] for name in ("甲", "乙")]
        self.assertEqual(self.request("/people", {"name": " 甲 "})[0], 409)
        def save(person, taste, revision):
            return self.request("/feedback", {"person_id": person, "cup": "brew-1", "revision": revision,
                                              "feedback": {"overall": 0, "taste": taste}})
        self.assertEqual(save(people[0], "略涩", 0)[0], 200)
        self.assertEqual(save(people[0], "略涩", 0), (200, {"revision": 1}))
        self.assertEqual(save(people[1], "甜", 0)[0], 200)
        with ThreadPoolExecutor(2) as pool:
            codes = list(pool.map(lambda taste: save(people[0], taste, 1)[0], ("凉后更甜", "余韵短")))
        self.assertEqual(sorted(codes), [200, 409])
        notes = {n["person_id"]: n for n in self.request("")[1]["notes"]}
        self.assertEqual(len(notes), 2)
        self.assertEqual(notes[people[1]]["feedback"], {"overall": 0, "taste": "甜"})
        self.assertEqual(notes[people[0]]["revision"], 2)
        with self.assertRaises(ValueError):
            delete_brew_record(1)

    def test_empty_invalid_and_missing_targets(self):
        person = self.request("/people", {"name": "试饮"})[1]["id"]
        data = {"person_id": person, "cup": "brew-1", "revision": 0, "feedback": {}}
        for feedback in ({}, {"taste": " "}, {"overall": True}, {"overall": 12}, {"unknown": "甜"}):
            self.assertEqual(self.request("/feedback", dict(data, feedback=feedback))[0], 400)
        data["feedback"] = {"sweetness": 7}
        for key, value in (("cup", "brew-99"), ("person_id", 900)):
            self.assertEqual(self.request("/feedback", dict(data, **{key: value}))[0], 404)
        self.assertEqual(self.request("")[1]["notes"], [])

    def test_inventory_and_brew_history_are_separate(self):
        with schema.get_db_connection() as db:
            for bean_id, name, weight in ((1, "旧库存", 0), (2, "新入库", 30), (3, "重量待补", None)):
                db.execute("""INSERT INTO beans(id,bean_name,roaster,process,plot,batch,
                              net_weight,price_total,created_at)
                              VALUES(?,?,'','','','',?,NULL,'')""", (bean_id, name, weight))
        result = self.request("")[1]
        self.assertEqual({b["id"] for b in result["inventory"]}, {2, 3})
        old_cup = next(c for c in result["cups"] if c["id"] == "brew-1")
        self.assertEqual(old_cup["bean_id"], 1)
        self.assertFalse(any(c.get("bean_id") == 2 for c in result["cups"]))
        client = HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            client.request("POST", "/api/brews", json.dumps({"bean_id": 2, "brew_date": "2026-11-06", "data": {}}),
                           {"Content-Type": "application/json"})
            response = client.getresponse()
            self.assertEqual(response.status, 201)
            cup = "brew-" + str(json.load(response)["item"]["id"])
        finally:
            client.close()
        self.assertEqual(next(c for c in self.request("")[1]["cups"] if c["id"] == cup)["bean_id"], 2)
        person = self.request("/people", {"name": "新品试饮"})[1]["id"]
        self.assertEqual(self.request("/feedback", {"person_id": person, "cup": cup,
                                                  "revision": 0, "feedback": {"overall": 7}})[0], 200)
