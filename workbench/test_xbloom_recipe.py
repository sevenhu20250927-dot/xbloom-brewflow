"""Offline recipe-contract regression tests; no real Bluetooth connection.

The v1 file is the user-reviewed historical recipe. Every altered document,
boundary recipe, file fault and client below is synthetic test input, not a
brew observation. Expected bytes are the already frozen old-encoder vectors.
"""
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from xbloom_bridge import protocol as p
from xbloom_bridge.__main__ import parser, run
from xbloom_bridge.recording import recipe_digest
from xbloom_bridge.transport import Session


ROOT = Path(__file__).resolve().parent
ARCHIVE = ROOT.parent / "tests/fixtures/legacy.recipe.json"
REVIEWED_DIGEST = "4e735a511aca3733aa3c76daca4348509ddd5574306228b22bbae7515b83c747"
ARCHIVE_FILE_DIGEST = "9c681e3fdfa9787acc7686d9639142756441a2d53e5bd60dc280b4c7eb008480"
FROZEN_FRAMES = [
    "580101a61f180000000100000000000000000f00000050fd",
    "580101a81f14000000010000dc420000b44221a1",
    "580101411f2700000001182d5e0202ec006e1e695e0200f80000235a5e01000000002333a0db9b",
]


def archived_recipe():
    return json.loads(ARCHIVE.read_text(encoding="utf-8"))


def at(value, path):
    for component in path:
        value = value[component]
    return value


def replacing(path, value):
    recipe = archived_recipe()
    at(recipe, path[:-1])[path[-1]] = value
    return recipe


def invalid_objects():
    """Named, deterministic counterexamples, independent of validator internals."""
    cases = []
    object_paths = [(), ("recipe",)] + [("recipe", "pours", i) for i in range(3)]
    for path in object_paths:
        source = at(archived_recipe(), path)
        for key in source:
            candidate = archived_recipe()
            del at(candidate, path)[key]
            cases.append((f"missing:{path}:{key}", candidate))
        for key in ("unexpected", "grinder_size", "temperature "):
            candidate = archived_recipe()
            at(candidate, path)[key] = 45
            cases.append((f"unknown:{path}:{key}", candidate))
        for wrong in (None, [], "object", 1, True):
            candidate = replacing(path, wrong) if path else wrong
            cases.append((f"container:{path}:{wrong!r}", candidate))
    numeric_paths = [("doseGrams",), ("recipe", "grinderSize"),
                     ("recipe", "rpm"), ("recipe", "grandWater")]
    for i in range(3):
        numeric_paths += [("recipe", "pours", i, name)
                         for name in ("volume", "temperature", "pattern", "pausing")]
    for path in numeric_paths:
        current = at(archived_recipe(), path)
        for wrong in (True, False, str(current), None, [], {}, float(current),
                      current + .5, math.nan, math.inf, -math.inf, 10 ** 1000):
            cases.append((f"integer:{path}:{str(wrong)[:30]}", replacing(path, wrong)))
    ranges = [(("doseGrams",), (0, 4, 19)),
              (("recipe", "grinderSize"), (0, 81)),
              (("recipe", "rpm"), (59, 61, 101, 121)),
              (("recipe", "grandWater"), (0, 501)),
              (("recipe", "pours", 0, "volume"), (0, 501)),
              (("recipe", "pours", 0, "temperature"), (19, 21, 39, 96, 97, 99)),
              (("recipe", "pours", 0, "pattern"), (-1, 3)),
              (("recipe", "pours", 0, "pausing"), (-1, 60))]
    for path, values in ranges:
        for value in values:
            cases.append((f"range:{path}:{value}", replacing(path, value)))
    for value in ("other", "XDRIPPER", "", None, True, 1, []):
        cases.append((f"cup:{value!r}", replacing(("cupType",), value)))
    for i in range(3):
        for key in ("vibBefore", "vibAfter"):
            for value in (0, 1, "true", "false", None, [], {}):
                cases.append((f"flag:{i}:{key}:{value!r}",
                              replacing(("recipe", "pours", i, key), value)))
        for value in (True, False, "3.0", None, [], {}, math.nan, math.inf,
                      -math.inf, 2.9, 3.6, 3.05, 3.000000001,
                      math.nextafter(3.0, 4.0), math.nextafter(3.5, 3.0), 10 ** 1000):
            cases.append((f"flow:{i}:{str(value)[:30]}",
                          replacing(("recipe", "pours", i, "flowRate"), value)))
    for value in (None, {}, "pours", (), [], [archived_recipe()["recipe"]["pours"][0]] * 10):
        cases.append((f"pours:{type(value).__name__}:{len(value) if value is not None else 0}",
                      replacing(("recipe", "pours"), value)))
    cases.append(("total-mismatch", replacing(("recipe", "grandWater"), 241)))
    candidate = replacing(("recipe", "pours", 2, "volume"), 91)
    candidate["recipe"]["grandWater"] = 241
    cases.append(("ratio-not-exact", candidate))
    candidate = archived_recipe()
    candidate["doseGrams"] = 5  # 240 ml / 5 g is beyond the encoded ratio byte.
    cases.append(("ratio-overflow", candidate))
    candidate = archived_recipe()
    candidate["recipe"]["grandWater"] = 63
    for pour in candidate["recipe"]["pours"]:
        pour["volume"] = 21
    # 63 / 15 = 4.2 is encodable, but firmware float32(4.2) * 15 is
    # 62.999996185302734; truncation would silently change the total to 62.
    cases.append(("firmware-float32-total-drift", candidate))
    for key in ("bypassMl", "bypassTempC"):
        candidate = archived_recipe()
        candidate[key] = 10 if key == "bypassMl" else 90
        cases.append((f"bypass-missing-pair:{key}", candidate))
    for key, invalid in (
            ("bypassMl", (-1, 501, True, False, 10.0, 10.5, "10", None, [], {}, math.nan, math.inf)),
            ("bypassTempC", (0, 20, 39, 96, 98, True, 90.0, "90", None, math.nan, math.inf))):
        for value in invalid:
            candidate = archived_recipe()
            candidate.update(bypassMl=10, bypassTempC=90)
            candidate[key] = value
            cases.append((f"bypass-invalid:{key}:{value!r}", candidate))
    for volume, temp in ((0, 90), (0, False), (0, 0.0), (261, 90)):
        candidate = archived_recipe()
        candidate.update(bypassMl=volume, bypassTempC=temp)
        cases.append((f"bypass-disabled-or-combined-limit:{volume}:{temp!r}", candidate))
    return cases


def invalid_documents():
    text = ARCHIVE.read_text(encoding="utf-8")
    cases = [
        ("duplicate-root", text.replace('"doseGrams": 15', '"doseGrams": 15, "doseGrams": 16')),
        ("duplicate-recipe", text.replace('"grinderSize": 51', '"grinderSize": 51, "grinderSize": 45')),
        ("duplicate-pour", text.replace('"volume": 45', '"volume": 45, "volume": 46', 1)),
        ("escaped-duplicate-key", text.replace('"grinderSize": 51',
                                              '"grinderSize": 51, "grinder\\u0053ize": 45')),
        ("trailing-object", text + "{}"),
        ("empty", ""), ("truncated", text[:-5]),
        ("comment", "// synthetic\n" + text),
        ("trailing-comma", text.replace('"doseGrams": 15,', '"doseGrams": 15,,')),
        ("deep-nesting", "[" * 2000 + "0" + "]" * 2000),
        ("oversized-number", text.replace('"doseGrams": 15', '"doseGrams": ' + "1" * 5000)),
        ("float-precision-loss", text.replace('"flowRate": 3.0', '"flowRate": 3.0000000000000001')),
        ("float-underflow", text.replace('"flowRate": 3.0', '"flowRate": 1e-9999')),
        ("extreme-exponent", text.replace('"flowRate": 3.0',
                                          '"flowRate": 1e-999999999999999999999999999999')),
        ("float-overflow", text.replace('"flowRate": 3.0', '"flowRate": 1e9999')),
    ]
    for token in ("NaN", "Infinity", "-Infinity"):
        cases.append((f"nonfinite:{token}", text.replace('"flowRate": 3.0', '"flowRate": ' + token)))
        cases.append((f"nonfinite-unknown:{token}", text.replace('"doseGrams": 15',
                                                                '"extra": ' + token + ', "doseGrams": 15')))
    return [(label, value.encode("utf-8")) for label, value in cases] + [
        ("invalid-utf8", b"\xff" + text.encode("utf-8")),
        ("utf8-bom", b"\xef\xbb\xbf" + text.encode("utf-8")),
        ("utf16", text.encode("utf-16")),
        ("too-large", text.encode("utf-8") + b" " * 65536),
    ]


class RecipeContractTests(unittest.TestCase):
    def test_native_bypass_matches_yiyi_legacy_encoding_and_keeps_pours(self):
        # Frozen software vectors from Yiyi's encoding path, NOT device captures.
        vectors = [(10, 90, "580101a61f1800000001000020410000b4420f0000000fff"),
                   (40, 92, "580101a61f1800000001000020420000b8420f000000fc18")]
        for volume, temp, expected in vectors:
            with self.subTest(volume=volume, temperature=temp):
                recipe = archived_recipe()
                recipe.update(bypassMl=volume, bypassTempC=temp)
                original = deepcopy(recipe)
                frames = p.build_recipe_frames(recipe)
                self.assertEqual(frames[0][0], "bypass+dose")
                self.assertEqual(frames[0][1].hex(), expected)
                self.assertEqual([frame.hex() for _, frame in frames[1:]], FROZEN_FRAMES[1:])
                self.assertEqual([int.from_bytes(frame[3:5], 'little') for _, frame in frames],
                                 [8102, 8104, 8001])
                self.assertEqual(recipe, original)
                self.assertEqual(p.parse_recipe(json.dumps(recipe).encode()), original)

    def test_explicit_bypass_off_preserves_legacy_bytes(self):
        recipe = archived_recipe()
        recipe.update(bypassMl=0, bypassTempC=0)
        self.assertEqual([frame.hex() for _, frame in p.build_recipe_frames(recipe)], FROZEN_FRAMES)

    def test_bypass_boundaries_and_combined_water_limit(self):
        for volume, temp in ((1, 40), (260, 95)):
            recipe = archived_recipe()  # 240 ml through; combined boundary is 500 ml.
            recipe.update(bypassMl=volume, bypassTempC=temp)
            frame = p.build_recipe_frames(recipe)[0][1]
            self.assertEqual(struct.unpack('<ffi', frame[10:-2]), (volume, temp, 15))

    def test_bypass_is_in_review_fingerprint(self):
        recipe = archived_recipe()
        before = recipe_digest(recipe)
        recipe.update(bypassMl=10, bypassTempC=90)
        first = recipe_digest(recipe)
        recipe['bypassMl'] = 11
        second = recipe_digest(recipe)
        recipe['bypassTempC'] = 91
        self.assertEqual(len({before, first, second, recipe_digest(recipe)}), 4)

    def test_215_plus_10_remains_rejected_without_silent_rescaling(self):
        recipe = archived_recipe()
        recipe.update(bypassMl=10, bypassTempC=90)
        sample = recipe['recipe']['pours'][0]
        recipe['recipe']['pours'] = [dict(sample, volume=v) for v in (45, 60, 60, 50)]
        recipe['recipe']['grandWater'] = 215
        before = deepcopy(recipe)
        with self.assertRaisesRegex(p.ProtocolError, 'ratio cannot be encoded exactly'):
            p.build_recipe_frames(recipe)
        self.assertEqual(recipe, before)

    def test_archived_recipe_bytes_digest_and_encoded_commands_unchanged(self):
        self.assertEqual(hashlib.sha256(ARCHIVE.read_bytes()).hexdigest(), ARCHIVE_FILE_DIGEST)
        recipe = p.load_recipe(ARCHIVE)
        self.assertEqual(recipe_digest(recipe), REVIEWED_DIGEST)
        original = deepcopy(recipe)
        self.assertEqual([frame.hex() for _, frame in p.build_recipe_frames(recipe)], FROZEN_FRAMES)
        self.assertEqual(recipe, original)

    def test_all_named_invalid_objects_rejected_without_mutation(self):
        for label, recipe in invalid_objects():
            with self.subTest(case=label):
                before = repr(recipe)
                with self.assertRaises(p.ProtocolError):
                    p.build_recipe_frames(recipe)
                self.assertEqual(repr(recipe), before)

    def test_all_named_invalid_documents_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "synthetic.recipe.json"
            for label, document in invalid_documents():
                with self.subTest(case=label):
                    path.write_bytes(document)
                    with self.assertRaises(p.ProtocolError):
                        p.load_recipe(path)

    def test_valid_numeric_and_enum_boundaries(self):
        cases = []
        for key, values in (("grinderSize", (1, 80)),
                            ("rpm", (60, 70, 80, 90, 100, 110, 120))):
            cases += [(key, value, replacing(("recipe", key), value)) for value in values]
        for key, values in (("temperature", (20, 40, 95, 98)),
                            ("pattern", (0, 1, 2)), ("pausing", (0, 59)),
                            ("flowRate", (3, 3.0, 3.1, 3.2, 3.3, 3.4, 3.5)),
                            ("vibBefore", (False, True)), ("vibAfter", (False, True))):
            cases += [(key, value, replacing(("recipe", "pours", 0, key), value)) for value in values]
        for key, value, recipe in cases:
            with self.subTest(field=key, value=value):
                before = deepcopy(recipe)
                self.assertEqual([label for label, _ in p.build_recipe_frames(recipe)], ["dose", "cup", "recipe"])
                self.assertEqual(recipe, before)

    def test_valid_dose_total_and_pour_count_boundaries(self):
        # These are encoding-boundary inputs, not recommendations for brewing.
        for dose, volumes in ((5, [80]), (18, [288]), (10, [1]),
                              (18, [459]), (15, [120, 120]),
                              (15, [15] * 9), (15, [127, 113]), (15, [128, 112])):
            with self.subTest(dose=dose, volumes=volumes):
                recipe = archived_recipe()
                sample = recipe["recipe"]["pours"][0]
                recipe["doseGrams"] = dose
                recipe["recipe"]["pours"] = [dict(sample, volume=v) for v in volumes]
                recipe["recipe"]["grandWater"] = sum(volumes)
                self.assertEqual(len(p.build_recipe_frames(recipe)), 3)

    def test_file_limit_accepts_exactly_64_kib_and_rejects_one_more_byte(self):
        raw = ARCHIVE.read_bytes()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "synthetic.recipe.json"
            path.write_bytes(raw + b" " * (65536 - len(raw)))
            self.assertEqual(p.load_recipe(path), archived_recipe())
            with path.open("ab") as stream:
                stream.write(b" ")
            with self.assertRaises(p.ProtocolError):
                p.load_recipe(path)

    def test_missing_file_and_directory_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            for path in (Path(temp) / "missing.json", Path(temp)):
                with self.subTest(path=path):
                    with self.assertRaises((p.ProtocolError, OSError)):
                        p.load_recipe(path)

    def test_invalid_path_does_not_consume_or_close_callers_file_descriptor(self):
        with tempfile.TemporaryFile() as stream:
            stream.write(ARCHIVE.read_bytes())
            stream.seek(0)
            for value in (stream.fileno(), True, None, []):
                with self.subTest(path=value):
                    with self.assertRaises(p.ProtocolError):
                        p.load_recipe(value)
                    os.fstat(stream.fileno())
                    self.assertEqual(stream.tell(), 0)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO only exists on supported Unix hosts")
    def test_fifo_rejected_without_waiting_for_a_writer(self):
        # A subprocess timeout makes a blocking file-read regression fail safely.
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "synthetic.fifo"
            os.mkfifo(path)
            code = ("import sys\nfrom xbloom_bridge.protocol import load_recipe, ProtocolError\n"
                    "try: load_recipe(sys.argv[1])\n"
                    "except (ProtocolError, OSError): sys.exit(0)\n"
                    "else: sys.exit(1)\n")
            result = subprocess.run([sys.executable, "-c", code, str(path)], cwd=ROOT,
                                    capture_output=True, text=True, timeout=3)
            self.assertEqual(result.returncode, 0, result.stderr)


class RecipeEntryPointTests(unittest.IsolatedAsyncioTestCase):
    async def test_bypass_preview_stays_offline_and_exposes_native_frame(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'synthetic-bypass.json'
            recipe = archived_recipe()
            recipe.update(bypassMl=10, bypassTempC=90)
            path.write_text(json.dumps(recipe))
            with patch('xbloom_bridge.__main__.Journal', side_effect=AssertionError('no journal')), \
                 patch('xbloom_bridge.__main__.Session', side_effect=AssertionError('no hardware')):
                result = await run(parser().parse_args(['preview', '--recipe', str(path)]))
            self.assertFalse(result['hardware_access'])
            self.assertEqual(result['recipe'], recipe)
            self.assertEqual(result['sha256'], recipe_digest(recipe))
            self.assertEqual(result['frames'][0]['hex'],
                             '580101a61f1800000001000020410000b4420f0000000fff')

    async def test_invalid_documents_rejected_before_cli_journal_or_session(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "synthetic.recipe.json"
            documents = invalid_documents()
            documents += [(label, json.dumps(recipe).encode()) for label, recipe in invalid_objects()]
            with patch("xbloom_bridge.__main__.Journal", side_effect=AssertionError("must not open journal")) as journal, \
                 patch("xbloom_bridge.__main__.Session", side_effect=AssertionError("must not construct session")) as session:
                for label, document in documents:
                    path.write_bytes(document)
                    for command in ("preview", "load", "brew"):
                        with self.subTest(case=label, command=command):
                            argv = [command, "--recipe", str(path)]
                            if command != "preview":
                                argv += ["--address", "synthetic-address"]
                            if command == "brew":
                                argv += ["--confirm-start", "--reviewed-sha256", REVIEWED_DIGEST]
                            with self.assertRaises(p.ProtocolError):
                                await run(parser().parse_args(argv))
                journal.assert_not_called()
                session.assert_not_called()

    async def test_invalid_dicts_rejected_before_session_any_write(self):
        for label, recipe in invalid_objects():
            with self.subTest(case=label):
                journal = Mock()
                session = Session("synthetic-address", journal)
                # No __aenter__: this client exists only in memory, no BLE import.
                client = SimpleNamespace(is_connected=True, write_gatt_char=AsyncMock())
                session.client = client
                session.events = [{"data": {"state": "idle"}}]
                with self.assertRaises(p.ProtocolError):
                    await session.load(recipe)
                client.write_gatt_char.assert_not_awaited()
                journal.append.assert_not_called()
                self.assertIsNone(session.loaded_digest)

    async def test_valid_preview_is_offline_and_returns_reviewed_fingerprint(self):
        with patch("xbloom_bridge.__main__.Journal", side_effect=AssertionError("must not open journal")), \
             patch("xbloom_bridge.__main__.Session", side_effect=AssertionError("must not construct session")):
            result = await run(parser().parse_args(["preview", "--recipe", str(ARCHIVE)]))
        self.assertFalse(result["hardware_access"])
        self.assertEqual(result["sha256"], REVIEWED_DIGEST)
        self.assertEqual([frame["hex"] for frame in result["frames"]], FROZEN_FRAMES)


if __name__ == "__main__":
    unittest.main()
