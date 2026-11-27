"""Synthetic offline recommendation contract checks; no model or business writes."""

import copy
import json
import unittest

from coffee_product import recommendations as rec


class RecommendationTests(unittest.TestCase):
    def setUp(self):
        self.state = {
            "people": [{"id": 1, "name": "模拟甲"}, {"id": 2, "name": "模拟乙"}],
            "preferences": [{"person_id": 1, "preference_text": "轻盈", "revision": 1},
                            {"person_id": 2, "preference_text": "浓郁，另一人专属原话", "revision": 2}],
            "beans": [{"id": i, "name": "同名测试豆" if i in (1, 2) else f"测试豆{i}",
                       "roaster": "测试烘焙商", "country": "测试产国", "process": "水洗",
                       "source_flavor": ["茶感", "柑橘"], "source_notes": "豆袋描述，不是品饮",
                       "net_weight": weight}
                      for i, weight in enumerate((20, 15, 10, None, 35, 40), start=1)],
            "brews": [{"id": 10, "bean_id": 1, "status": "completed", "created_at": "2026-11-01"},
                      {"id": 11, "bean_id": 3, "status": "completed", "created_at": "2026-11-02"},
                      {"id": 12, "bean_id": 2, "status": "cancelled", "created_at": "2026-11-03"}],
            "feedback": [{"person_id": 1, "cup": "brew-10", "revision": 2, "feedback": {"overall": 0, "taste": "本人原话：凉后更清晰"}},
                         {"person_id": 2, "cup": "brew-10", "revision": 1, "feedback": {"taste": "另一人专属评价"}},
                         {"person_id": 1, "cup": "brew-11", "revision": 1, "feedback": {"taste": "本人旧库存体验"}},
                         {"person_id": 1, "cup": "brew-12", "revision": 1, "feedback": {"taste": "取消杯不得纳入"}},
                         {"person_id": 1, "cup": "brew-999", "revision": 1, "feedback": {"taste": "无关联杯不得纳入"}}],
        }
        self.context = rec.build_context(self.state, person_id=1)

    def output(self, context=None):
        context = context or self.context
        items = []
        for bean in context["candidates"][:context["selection_count"]["min"]]:
            ids = list(context["required_citations_by_bean"][str(bean["id"])])
            if not items:
                ids.extend(context["required_citations"])
                ids.extend(context["personal_feedback_sources"][:1])
            items.append({"bean_id": bean["id"], "reason": "测试匹配假设，真实喜好待本人反馈。",
                          "story": "豆袋标注茶感与柑橘；这是测试豆卡介绍。",
                          "citations": [{"source_id": source_id, "quote": context["sources"][source_id]["content"][:100]}
                                        for source_id in dict.fromkeys(ids)]})
        return {"person_id": context["request"]["person_id"], "items": items}

    def validate(self, output, context=None):
        return rec.validate_output(json.dumps(output, ensure_ascii=False), context or self.context,
                                   provider="codex", model="offline-fixture")

    def test_context_preserves_person_words_and_joins_feedback_by_brew_id(self):
        before = copy.deepcopy(self.state)
        context = rec.build_context(self.state, person_id=1)
        self.assertEqual(context["task"], "recommendation")
        self.assertEqual(context["request"], {"person_id": 1})
        self.assertEqual([b["id"] for b in context["candidates"]], [1, 2, 5, 6])
        self.assertEqual(context["history"]["personal_feedback_count"], 2)
        self.assertIn("轻盈", context["sources"]["preference:1"]["content"])
        self.assertEqual(context["sources"]["feedback:10:1"]["bean_id"], 1)
        self.assertIn('"overall": 0', context["sources"]["feedback:10:1"]["content"])
        self.assertNotIn("feedback:10:2", context["sources"])
        serialized = json.dumps(context, ensure_ascii=False)
        for excluded in ("另一人专属", "取消杯不得纳入", "无关联杯不得纳入"):
            self.assertNotIn(excluded, serialized)
        self.assertIn("bean:3", context["sources"])
        self.assertEqual(context["required_citations_by_bean"]["2"], ["bean:2"])
        self.assertEqual(self.state, before)

    def test_schema_and_valid_output_map_only_verified_ids_and_quotes(self):
        schema = rec.output_schema(self.context)
        self.assertEqual(schema["properties"]["items"]["items"]["properties"]["bean_id"]["enum"], [1, 2, 5, 6])
        self.assertFalse(schema["additionalProperties"])
        result = self.validate(self.output())
        self.assertEqual(set(result), {"person_id", "items", "provenance"})
        self.assertEqual(result["person_id"], 1)
        self.assertEqual([item["bean_id"] for item in result["items"]], [1, 2, 5])
        self.assertEqual(set(result["items"][0]), {"bean_id", "reason", "story", "evidence"})
        self.assertIn("offline-fixture", result["provenance"])
        self.assertTrue(any("preference:1" in e["title"] for e in result["items"][0]["evidence"]))

    def test_rejects_wrong_person_unavailable_unknown_duplicate_and_wrong_counts(self):
        changes = [lambda out: out.update(person_id=2),
                   lambda out: out["items"][0].update(bean_id=3),
                   lambda out: out["items"][0].update(bean_id=999),
                   lambda out: out["items"][1].update(bean_id=1),
                   lambda out: out["items"][0].update(bean_id=True),
                   lambda out: out.update(items=out["items"][:2]),
                   lambda out: out["items"][0].update(name="模型伪造豆名")]
        for change in changes:
            output = self.output()
            change(output)
            with self.subTest(output=output), self.assertRaises(ValueError):
                self.validate(output)

    def test_rejects_invented_quotes_other_people_and_missing_personal_evidence(self):
        bad = self.output()
        bad["items"][0]["citations"][0]["quote"] = "不存在的获奖经历"
        with self.assertRaises(ValueError):
            self.validate(bad)
        bad = self.output()
        bad["items"][0]["citations"][0]["source_id"] = "feedback:10:2"
        with self.assertRaises(ValueError):
            self.validate(bad)
        for prefix in ("preference:", "feedback:"):
            bad = self.output()
            for item in bad["items"]:
                item["citations"] = [c for c in item["citations"] if not c["source_id"].startswith(prefix)]
            with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                self.validate(bad)

    def test_insufficient_inventory_returns_actual_count_and_zero_stays_empty(self):
        for count in (0, 1, 2):
            state = copy.deepcopy(self.state)
            state["beans"] = state["beans"][:count]
            context = rec.build_context(state, person_id=1)
            self.assertEqual(context["selection_count"], {"min": count, "max": count})
            self.assertEqual(len(self.validate(self.output(context), context)["items"]), count)

    def test_no_feedback_or_preference_remains_unknown_and_never_borrows_other_person(self):
        state = copy.deepcopy(self.state)
        state["feedback"] = [item for item in state["feedback"] if item["person_id"] == 2]
        state["preferences"] = [item for item in state["preferences"] if item["person_id"] == 2]
        context = rec.build_context(state, person_id=1)
        self.assertEqual(context["required_citations"], [])
        self.assertEqual(context["personal_feedback_sources"], [])
        self.assertIn("未知", context["history"]["note"])
        self.assertNotIn("另一人专属", json.dumps(context, ensure_ascii=False))
        self.assertEqual(len(self.validate(self.output(context), context)["items"]), 3)
        prompt = rec.build_prompt(context)
        self.assertIn("不能直接等同浓度", prompt)
        self.assertIn("不虚构庄园历史", prompt)
        self.assertIn("豆袋", prompt)

    def test_invalid_identity_and_duplicate_json_keys_are_rejected(self):
        for person_id in (True, 999, "1", None):
            with self.subTest(person_id=person_id), self.assertRaises(ValueError):
                rec.build_context(self.state, person_id=person_id)
        raw = json.dumps(self.output(), ensure_ascii=False)
        with self.assertRaises(ValueError):
            rec.validate_output(raw.replace('"person_id": 1', '"person_id": 1, "person_id": 2', 1), self.context)


if __name__ == "__main__":
    unittest.main(verbosity=2)
