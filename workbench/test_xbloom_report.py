"""Synthetic offline checks; no Bluetooth, inventory, or physical brew."""
import asyncio
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from xbloom_bridge.report import build_report, generate_report, render_svg
from xbloom_bridge.recording import recipe_digest
from xbloom_bridge.__main__ import parser, run


def recipe():
    return {'cupType': 'xdripper', 'doseGrams': 15, 'recipe': {
        'grandWater': 240, 'grinderSize': 51, 'rpm': 60,
        'pours': [dict(volume=v, temperature=93, flowRate=3.5, pattern=2,
                       pausing=8, vibBefore=False, vibAfter=True) for v in (45, 105, 90)]}}


def decoded(t, **data):
    return dict(kind='decoded', elapsed_s=t+10, received_elapsed_s=t, data=data)


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root/'synthetic.jsonl'

    def write(self, events, tail=''):
        self.path.write_text('\n'.join(json.dumps(e) for e in events)+'\n'+tail)
        return self.path

    def session(self):
        return dict(kind='session', recipe=recipe(), operation='brew',
                    wall_utc='2026-11-09T00:00:00+00:00')

    def test_missing_truncated_no_fabrication(self):
        self.write([self.session(), {'kind': 'error', 'error': 'synthetic disconnect'}], '{broken')
        before = self.path.read_bytes()
        result = generate_report(self.path)
        text = Path(result['html']).read_text()
        self.assertIn('暂无可绘制', text)
        self.assertIn('异常记录', text)
        self.assertIn('日志第 3 行损坏', text)
        self.assertEqual(before, self.path.read_bytes())
        self.assertFalse(result['hardware_access'])
        self.assertEqual(result['completion'], 'unconfirmed')
        ET.fromstring(Path(result['svg']).read_text())

    def test_candidate_freezes_report_before_idle_and_cup_removal(self):
        self.write([self.session(), decoded(100, code=40510), decoded(110, coffee_g=1),
                    decoded(115, code=40511), decoded(120, code=40512),
                    decoded(125, coffee_g=20), decoded(130, state='idle'),
                    decoded(140, coffee_g=0), decoded(150, code=40510)])
        data = build_report(self.path)
        self.assertEqual(data['candidate'], 20)
        self.assertEqual(data['coffee'], [(10, 1)])
        self.assertEqual(data['stages'], [0])
        svg = render_svg(data)
        self.assertIn('0:20', svg)
        self.assertIn('屏显计时 / 最后一滴', svg)
        self.assertNotIn('事件2', svg)

    def test_spike_rule_retains_broad_peaks_endpoints_and_raw(self):
        self.write([self.session(), decoded(0, code=40510)] +
                   [decoded(t, coffee_g=v) for t, v in
                    [(1, 10), (1.4, 30), (1.8, 10.3), (4, 40), (9, 10.4), (10, 70)]])
        before = self.path.read_bytes()
        data = build_report(self.path)
        self.assertEqual([v for _, v in data['coffee']], [10, 10.3, 40, 10.4, 70])
        self.assertIn('1 个孤立', ' '.join(data['warnings']))
        self.assertEqual(before, self.path.read_bytes())

    def test_dynamic_pours_axes_and_escaped_text(self):
        events = [self.session(), decoded(0, code=40510), decoded(800, coffee_g=450)]
        events[0]['recipe']['recipe']['pours'] *= 2
        self.write(events)
        result = generate_report(self.path, title='<script>alert("x")</script>', brewer='<img>')
        html = Path(result['html']).read_text()
        self.assertNotIn('<script>', html)
        self.assertIn('第6段', html)
        self.assertIn('450.0', html)
        ET.fromstring(Path(result['svg']).read_text())

    def test_duplicate_time_nan_and_water_reset(self):
        self.write([self.session(), decoded(0, code=40510), decoded(1, water_g=45),
                    decoded(2, water_g=100), decoded(3, water_g=0),
                    decoded(1, coffee_g=2), decoded(1, coffee_g=3), decoded(2, coffee_g=float('nan'))])
        data = build_report(self.path)
        self.assertEqual(data['coffee'], [(1, 3)])
        self.assertEqual(data['water'], [(1, 45), (2, 100)])
        self.assertIn('无效读数', ' '.join(data['warnings']))

    def test_offline_command_never_creates_session(self):
        self.write([self.session()])
        with patch('xbloom_bridge.__main__.Session', side_effect=AssertionError('hardware')):
            result = asyncio.run(run(parser().parse_args(['report', str(self.path)])))
        self.assertTrue(Path(result['svg']).exists())

    def test_multiple_sessions_rejected(self):
        self.write([self.session(), self.session()])
        with self.assertRaisesRegex(ValueError, '一个会话'):
            generate_report(self.path)

    def test_bypass_report_separates_setpoints_and_does_not_invent_a_fifth_event(self):
        session = self.session()
        session['recipe'].update(bypassMl=10, bypassTempC=90)
        settings = session['recipe']['recipe']
        settings['grandWater'] = 216
        sample = settings['pours'][0]
        settings['pours'] = [dict(sample, volume=v) for v in (45, 60, 60, 51)]
        self.write([session] + [decoded(t, code=40510) for t in (0, 30, 60, 90)] +
                   [decoded(100, coffee_g=170), decoded(110, code=40512), decoded(120, state='idle')])
        before = self.path.read_bytes()
        result = generate_report(self.path)
        svg = Path(result['svg']).read_text()
        self.assertIn('226 ml', svg)
        self.assertIn('原生旁通', svg)
        self.assertIn('过粉 216 ml', svg)
        self.assertIn('10 ml', svg)
        self.assertIn('90℃', svg)
        self.assertIn('1:15.0667', svg)
        self.assertIn('4 / 4', svg)
        self.assertIn('事件4', svg)
        self.assertNotIn('事件5', svg)
        self.assertNotIn('第5段', svg)
        self.assertIn('不按事件序号推定旁通完成', svg)
        self.assertEqual(result['completion'], 'unconfirmed')
        self.assertEqual(self.path.read_bytes(), before)
        ET.fromstring(svg)

    def test_legacy_report_does_not_add_bypass_row(self):
        self.write([self.session()])
        svg = render_svg(build_report(self.path))
        self.assertIn('240 ml', svg)
        self.assertIn('1:16', svg)
        self.assertNotIn('原生旁通', svg)

    def exercise_brew(self, failure=None, report_failure=False):
        rec = recipe()
        recipe_path = self.root/'recipe.json'
        recipe_path.write_text(json.dumps(rec))
        args = parser().parse_args(['brew', '--address', 'synthetic', '--recipe', str(recipe_path),
                                    '--output', str(self.root/'runs'), '--reviewed-sha256', recipe_digest(rec),
                                    '--confirm-start', '--report-title', '模拟豆子', '--brewer', '模拟滤杯'])

        class FakeSession:
            def __init__(self, address, journal):
                self.journal = journal
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                self.journal.append('disconnected', expected=True)
            async def read_device_information(self):
                pass
            async def handshake(self):
                pass
            async def load(self, recipe):
                pass
            async def start(self, digest, authorized):
                self.journal.append('start_commit')
            async def observe_brew(self, seconds):
                if failure:
                    raise failure
                self.journal.append('decoded', data={'code': 40510})
                return 'program_end'

        with contextlib.ExitStack() as stack:
            stack.enter_context(patch('xbloom_bridge.__main__.Session', FakeSession))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            if report_failure:
                stack.enter_context(patch('xbloom_bridge.report.generate_report', side_effect=OSError('synthetic disk error')))
            return asyncio.run(run(args))

    def test_brew_automatically_generates_report(self):
        result = self.exercise_brew()
        svg = Path(result['report']['svg']).read_text()
        self.assertIn('模拟豆子', svg)
        self.assertIn('模拟滤杯', svg)
        self.assertEqual(result['event_counts']['start_commit'], 1)

    def test_failure_still_reports_and_preserves_original_error(self):
        with self.assertRaisesRegex(RuntimeError, 'synthetic brew error'):
            self.exercise_brew(RuntimeError('synthetic brew error'))
        self.assertEqual(len(list((self.root/'runs/reports').glob('*.svg'))), 1)

    def test_interrupt_still_reports(self):
        with self.assertRaises(KeyboardInterrupt):
            self.exercise_brew(KeyboardInterrupt())
        self.assertEqual(len(list((self.root/'runs/reports').glob('*.svg'))), 1)

    def test_report_failure_does_not_hide_capture_failure(self):
        with self.assertRaisesRegex(RuntimeError, 'original'):
            self.exercise_brew(RuntimeError('original'), report_failure=True)

    def test_report_failure_visible_without_restarting(self):
        result = self.exercise_brew(report_failure=True)
        self.assertIn('synthetic disk error', result['report']['error'])
        self.assertEqual(result['event_counts']['start_commit'], 1)


if __name__ == '__main__':
    unittest.main()
