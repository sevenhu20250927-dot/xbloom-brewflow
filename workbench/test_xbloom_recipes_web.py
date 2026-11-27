"""Offline xBloom recipe web/store tests, isolated from real inventory and BLE.

Only the baseline recipe is a historical user-reviewed file. All names, modified
recipes, file faults and HTTP requests here are synthetic. A socket-shaped
BytesIO object exercises the actual HTTP handler without binding a port.
"""
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import quote

from coffeeSys import CoffeeInventoryHandler
from test_xbloom_recipe import ARCHIVE, REVIEWED_DIGEST, invalid_documents, invalid_objects
from xbloom_bridge.protocol import load_recipe, parse_recipe
from xbloom_bridge.recording import recipe_digest
from xbloom_recipes import RecipeStore


class MemorySocket:
    def __init__(self, request):
        self.incoming = io.BytesIO(request)
        self.outgoing = bytearray()
        self.timeout = None

    def makefile(self, mode, buffering=None):
        if mode != "rb":
            raise AssertionError("HTTP tests must use the handler's normal socket writer")
        return self.incoming

    def sendall(self, data):
        self.outgoing.extend(data)

    def settimeout(self, value):
        self.timeout = value

    def gettimeout(self):
        return self.timeout


class RecipeStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "recipes"
        self.root.mkdir()
        self.store = RecipeStore(self.root)
        self.raw = ARCHIVE.read_bytes()

    def test_create_get_list_preserve_machine_format_and_digest(self):
        self.assertEqual(self.store.list(), {"items": [], "errors": []})
        item = self.store.create("水洗耶加-v1", self.raw)
        self.assertEqual(item["name"], "水洗耶加-v1")
        self.assertEqual(item["filename"], "水洗耶加-v1.recipe.json")
        self.assertEqual(item["recipe"], json.loads(self.raw))
        self.assertEqual(item["sha256"], REVIEWED_DIGEST)
        self.assertEqual(self.store.get(item["name"]), item)
        self.assertEqual(self.store.list(), {"items": [item], "errors": []})
        stored = load_recipe(self.root / item["filename"])
        self.assertEqual(set(stored), {"cupType", "doseGrams", "recipe"})
        self.assertEqual(recipe_digest(stored), REVIEWED_DIGEST)

    def test_same_name_rejected_without_changing_original(self):
        self.store.create("synthetic-v1", self.raw)
        path = self.root / "synthetic-v1.recipe.json"
        original = path.read_bytes()
        changed = json.loads(self.raw)
        changed["recipe"]["grinderSize"] = 52
        with self.assertRaises(FileExistsError):
            self.store.create("synthetic-v1", json.dumps(changed).encode())
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(len(list(self.root.iterdir())), 1)

    def test_download_preserves_stored_bytes_and_reviewed_digest(self):
        # Preserve both the historical bytes and other valid lexical forms.
        # Serializing in JavaScript would change 3.0 to 3 and alter the digest;
        # reformatting here would also lose the 3.00/whitespace variant.
        variants = (self.raw, b"\n  " + self.raw.replace(b'"flowRate": 3.0', b'"flowRate": 3.00', 1))
        for index, original in enumerate(variants):
            name = f"download-{index}"
            (self.root / f"{name}.recipe.json").write_bytes(original)
            with self.subTest(variant=index):
                downloaded = self.store.download(name)
                self.assertEqual(downloaded, original)
                self.assertEqual(recipe_digest(parse_recipe(downloaded)), REVIEWED_DIGEST)

    def test_download_rejects_invalid_stored_documents(self):
        path = self.root / "broken-v1.recipe.json"
        for label, raw in invalid_documents():
            with self.subTest(case=label):
                path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    self.store.download("broken-v1")

    def test_concurrent_same_name_has_exactly_one_winner(self):
        gate = threading.Barrier(6)

        def attempt(number):
            recipe = json.loads(self.raw)
            recipe["recipe"]["grinderSize"] = 50 + number
            gate.wait(timeout=5)
            try:
                return self.store.create("concurrent-v1", json.dumps(recipe).encode())
            except FileExistsError:
                return None

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(attempt, range(6)))
        winners = [item for item in results if item is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(self.store.get("concurrent-v1"), winners[0])
        self.assertEqual([p.name for p in self.root.iterdir()], ["concurrent-v1.recipe.json"])

    def test_failed_publish_or_flush_leaves_no_partial_recipe(self):
        for operation in ("link", "fsync"):
            with self.subTest(operation=operation):
                with patch(f"xbloom_recipes.os.{operation}", side_effect=OSError("synthetic write failure")):
                    with self.assertRaises(OSError):
                        self.store.create("failed-v1", self.raw)
                self.assertEqual(list(self.root.iterdir()), [])

    def test_directory_sync_failure_keeps_complete_published_recipe_for_recovery(self):
        # A disk error after publish is uncertain, not permission to overwrite or
        # invent another version on retry. The complete file remains readable.
        with patch("xbloom_recipes.os.fsync", side_effect=[None, OSError("synthetic directory sync failure")]):
            with self.assertRaises(OSError):
                self.store.create("uncertain-v1", self.raw)
        item = self.store.get("uncertain-v1")
        self.assertEqual(item["sha256"], REVIEWED_DIGEST)
        self.assertEqual([p.name for p in self.root.iterdir()], ["uncertain-v1.recipe.json"])
        with self.assertRaises(FileExistsError):
            self.store.create("uncertain-v1", self.raw)

    def test_names_are_bounded_and_cannot_address_other_paths(self):
        bad_names = ("", ".", "..", "../escape", "a/b", "a\\b", "/absolute",
                     "a%2fb", "a.recipe.json", " leading", "trailing ",
                     "a\n", "a\x00", "-leading", "_leading", "validate", "a" * 81,
                     None, 1, True, [])
        for name in bad_names:
            with self.subTest(name=repr(name)):
                with self.assertRaises(ValueError):
                    self.store.create(name, self.raw)
                with self.assertRaises(ValueError):
                    self.store.get(name)
        self.assertEqual(list(self.root.iterdir()), [])
        self.store.create("a" * 80, self.raw)

    def test_bad_files_are_reported_without_hiding_valid_recipes(self):
        good = self.store.create("valid-v1", self.raw)
        (self.root / "broken-v1.recipe.json").write_bytes(b'{"broken": true}')
        (self.root / "README.md").write_text("synthetic ignored document")
        result = self.store.list()
        self.assertEqual(result["items"], [good])
        self.assertEqual([row["filename"] for row in result["errors"]], ["broken-v1.recipe.json"])
        self.assertTrue(result["errors"][0]["error"])

    @unittest.skipUnless(hasattr(os, "symlink"), "requires symbolic links")
    def test_symbolic_link_is_not_read_or_replaced(self):
        outside = Path(self.temp.name) / "outside.recipe.json"
        outside.write_bytes(self.raw)
        target = self.root / "linked-v1.recipe.json"
        target.symlink_to(outside)
        with self.assertRaises((ValueError, OSError)):
            self.store.get("linked-v1")
        with self.assertRaises((ValueError, OSError)):
            self.store.download("linked-v1")
        with self.assertRaises(FileExistsError):
            self.store.create("linked-v1", self.raw)
        result = self.store.list()
        self.assertEqual(result["items"], [])
        self.assertEqual([row["filename"] for row in result["errors"]], [target.name])
        self.assertTrue(target.is_symlink())
        self.assertEqual(outside.read_bytes(), self.raw)


class RecipeHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "recipes"
        self.root.mkdir()
        self.store = RecipeStore(self.root)
        self.raw = ARCHIVE.read_bytes()
        self.handler = type("IsolatedRecipeHandler", (CoffeeInventoryHandler,), {"recipe_store": self.store})

    def request(self, method, path, body=b"", headers=None, *, default_headers=True, decode_json=True):
        pairs = [("Host", "localhost")]
        if default_headers and method in ("POST", "PUT", "DELETE"):
            pairs += [("Content-Type", "application/json"), ("Content-Length", str(len(body)))]
        pairs += headers or []
        head = f"{method} {path} HTTP/1.0\r\n" + "".join(f"{key}: {value}\r\n" for key, value in pairs)
        connection = MemorySocket(head.encode("ascii") + b"\r\n" + body)
        self.handler(connection, ("127.0.0.1", 12345),
                     SimpleNamespace(server_name="localhost", server_port=80))
        header, payload = bytes(connection.outgoing).split(b"\r\n\r\n", 1)
        status = int(header.split(b"\r\n", 1)[0].split()[1])
        response_headers = {}
        for line in header.split(b"\r\n")[1:]:
            key, value = line.split(b":", 1)
            response_headers[key.lower().decode()] = value.strip().decode()
        if decode_json and "application/json" in response_headers.get("content-type", ""):
            payload = json.loads(payload)
        return status, payload, response_headers

    def test_page_validation_creation_read_and_list(self):
        status, page, _ = self.request("GET", "/xb-recipes")
        self.assertEqual(status, 200)
        self.assertIn(b'/static/app.js', page)
        status, result, _ = self.request("POST", "/api/xb-recipes/validate", self.raw)
        self.assertEqual(status, 200)
        self.assertEqual(result["sha256"], REVIEWED_DIGEST)
        self.assertEqual(result["recipe"], json.loads(self.raw))
        self.assertEqual(result["ratio"], 16)
        self.assertEqual(list(self.root.iterdir()), [])
        route = "/api/xb-recipes/" + quote("水洗耶加-v1")
        status, result, _ = self.request("POST", route, self.raw, [("Origin", "http://localhost")])
        self.assertEqual(status, 201)
        item = result["item"]
        self.assertEqual(item["name"], "水洗耶加-v1")
        self.assertEqual(self.request("GET", route)[:2], (200, {"item": item}))
        self.assertEqual(self.request("GET", "/api/xb-recipes")[:2],
                         (200, {"items": [item], "errors": []}))
        self.assertEqual(self.request("POST", route, self.raw)[0], 409)

    def test_all_invalid_inputs_rejected_at_validate_and_create(self):
        documents = invalid_documents()
        documents += [(label, json.dumps(recipe).encode()) for label, recipe in invalid_objects()]
        for label, raw in documents:
            for route in ("/api/xb-recipes/validate", "/api/xb-recipes/invalid-v1"):
                with self.subTest(case=label, route=route):
                    status, payload, _ = self.request("POST", route, raw)
                    self.assertIn(status, (400, 413))
                    self.assertTrue(payload.get("error"))
                    self.assertEqual(list(self.root.iterdir()), [])

    def test_download_returns_original_bytes_digest_and_encoded_chinese_filename(self):
        name = "水洗耶加-v1"
        (self.root / f"{name}.recipe.json").write_bytes(self.raw)
        status, body, headers = self.request("GET", "/api/xb-recipes/" + quote(name) + "/download",
                                             decode_json=False)
        self.assertEqual(status, 200)
        self.assertEqual(body, self.raw)
        self.assertEqual(recipe_digest(parse_recipe(body)), REVIEWED_DIGEST)
        self.assertEqual(int(headers["content-length"]), len(self.raw))
        self.assertIn("application/json", headers["content-type"])
        self.assertTrue(headers["content-disposition"].startswith("attachment;"))
        self.assertIn("filename*=UTF-8''" + quote(name + ".recipe.json", safe=""),
                      headers["content-disposition"])
        self.assertNotIn(name, headers["content-disposition"])

    def test_download_bad_or_missing_file_returns_error_without_attachment(self):
        path = self.root / "broken-v1.recipe.json"
        for label, raw in invalid_documents():
            with self.subTest(case=label):
                path.write_bytes(raw)
                status, body, headers = self.request("GET", "/api/xb-recipes/broken-v1/download")
                self.assertEqual(status, 400)
                self.assertTrue(body.get("error"))
                self.assertNotIn("content-disposition", headers)
        status, body, headers = self.request("GET", "/api/xb-recipes/missing-v1/download")
        self.assertEqual(status, 404)
        self.assertTrue(body.get("error"))
        self.assertNotIn("content-disposition", headers)

    def test_malformed_headers_reject_without_writes(self):
        good = [("Content-Type", "application/json"), ("Content-Length", str(len(self.raw)))]
        cases = [
            ("missing-length", [("Content-Type", "application/json")], 411),
            ("missing-type", [("Content-Length", str(len(self.raw)))], 415),
            ("form-type", [("Content-Type", "application/x-www-form-urlencoded"), good[1]], 415),
            ("text-type", [("Content-Type", "text/plain"), good[1]], 415),
            ("negative-length", [good[0], ("Content-Length", "-1")], 400),
            ("zero-length", [good[0], ("Content-Length", "0")], 400),
            ("invalid-length", [good[0], ("Content-Length", "abc")], 400),
            ("fractional-length", [good[0], ("Content-Length", "1.5")], 400),
            ("oversized", [good[0], ("Content-Length", "65537")], 413),
            ("duplicate-length", good + [good[1]], 400),
            ("huge-length", [good[0], ("Content-Length", "9" * 5000)], 413),
            ("duplicate-type", good + [good[0]], 415),
            ("unsupported-charset", [("Content-Type", "application/json; charset=utf-16"), good[1]], 415),
            ("chunked", good + [("Transfer-Encoding", "chunked")], 400),
            ("truncated", [good[0], ("Content-Length", str(len(self.raw) + 1))], 400),
            ("cross-origin", good + [("Origin", "http://evil.example")], 403),
            ("null-origin", good + [("Origin", "null")], 403),
            ("duplicate-origin", good + [("Origin", "http://localhost"), ("Origin", "http://localhost")], 403),
        ]
        for name, headers, expected in cases:
            with self.subTest(case=name):
                status, body, _ = self.request("POST", "/api/xb-recipes/invalid-v1", self.raw,
                                               headers, default_headers=False)
                self.assertEqual(status, expected)
                self.assertTrue(body.get("error"))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_paths_not_found_and_immutable_methods(self):
        for path in ("/api/xb-recipes/%2e%2e%2fescape", "/api/xb-recipes/a%2fb",
                     "/api/xb-recipes/a%5cb", "/api/xb-recipes/%00", "/api/xb-recipes/a.recipe.json"):
            for method in ("GET", "POST"):
                with self.subTest(path=path, method=method):
                    self.assertEqual(self.request(method, path, self.raw if method == "POST" else b"")[0], 400)
        self.assertEqual(self.request("GET", "/api/xb-recipes/missing-v1")[0], 404)
        # The namespace exists; creating without a name is a malformed request.
        self.assertEqual(self.request("POST", "/api/xb-recipes", self.raw)[0], 400)
        self.store.create("existing-v1", self.raw)
        path = self.root / "existing-v1.recipe.json"
        before = path.read_bytes()
        for method in ("PUT", "DELETE"):
            status, _, _ = self.request(method, "/api/xb-recipes/existing-v1", self.raw)
            self.assertIn(status, (404, 405))
            self.assertEqual(path.read_bytes(), before)

    def test_storage_failure_is_reported_as_server_error(self):
        with patch.object(self.store, "create", side_effect=OSError("synthetic storage failure")):
            status, body, _ = self.request("POST", "/api/xb-recipes/failure-v1", self.raw)
        self.assertEqual(status, 500)
        self.assertTrue(body.get("error"))
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
