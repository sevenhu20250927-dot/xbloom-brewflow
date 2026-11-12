"""Synthetic release checks, temporary files only; no device or inventory."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from xbloom_bridge.history import build_history
from xbloom_bridge.report import build_report, render_svg

PACKAGE = Path(__file__).resolve().parents[1]


def session(title='模拟豆'):
    return [dict(kind='session', operation='brew', wall_utc='2026-01-01T00:00:00+00:00',
                 recipe=json.loads((PACKAGE/'examples/standard.recipe.json').read_text())),
            dict(kind='report_context', title=title)]


def write_log(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(json.dumps(x) for x in rows)+'\n')
    return path


def event(t, **data):
    return dict(kind='decoded', elapsed_s=t+100, received_elapsed_s=t, data=data)


class PortableEntryTests(unittest.TestCase):
    def cli(self, *args):
        with tempfile.TemporaryDirectory(prefix='xbloom unrelated cwd ') as tmp:
            env = dict(os.environ)
            env.pop('PYTHONPATH', None)
            env['PYTHONDONTWRITEBYTECODE'] = '1'
            return subprocess.run([sys.executable, '-B', str(PACKAGE/'scripts/xbloom.py'), *args],
                                  cwd=tmp, env=env, text=True, capture_output=True, timeout=10)

    def test_examples_work_from_unrelated_directory(self):
        for name in ('standard.recipe.json', 'bypass.recipe.json'):
            result = self.cli('preview', '--recipe', str(PACKAGE/'examples'/name))
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertFalse(data['hardware_access'])
            self.assertEqual(len(data['frames']), 3)

    def test_wrong_digest_refuses_before_connect_or_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'must-not-exist'
            result = self.cli('brew', '--address', 'SYNTHETIC-NOT-A-DEVICE',
                              '--recipe', str(PACKAGE/'examples/standard.recipe.json'),
                              '--reviewed-sha256', 'wrong', '--confirm-start', '--output', str(output))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Reviewed recipe digest', result.stderr)
            self.assertFalse(output.exists())

    def test_report_and_history_do_not_need_bluetooth(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_log(Path(tmp)/'offline.jsonl', session()+[dict(kind='error', error='synthetic')])
            result = self.cli('history', tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((Path(tmp)/'index.html').is_file())
            self.assertTrue((Path(tmp)/'reports/offline.svg').is_file())


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_failed_retry_and_observe_are_distinct(self):
        write_log(self.root/'fail.jsonl', session()+[dict(kind='error', error='no reply')])
        write_log(self.root/'retry.jsonl', session()+[dict(kind='start_observed')])
        write_log(self.root/'observe.jsonl', [dict(kind='session', operation='observe')])
        first = build_history(self.root)
        second = build_history(self.root)
        self.assertEqual(first['entries'], 2)
        self.assertEqual(second['entries'], 2)
        text = (self.root/'index.html').read_text()
        self.assertIn('未发启动 · 异常', text)
        self.assertIn('有启动记录', text)
        self.assertNotIn('observe.html', text)

    def test_scope_skips_external_symlinks_and_preserves_evidence(self):
        chosen = self.root/'chosen'
        own = write_log(chosen/'logs/own.jsonl', session('own'))
        external = write_log(self.root/'outside/private.jsonl', session('PRIVATE-TITLE'))
        before = own.read_bytes()
        (chosen/'shortcut').symlink_to(external.parent, target_is_directory=True)
        (chosen/'leak.jsonl').symlink_to(external)
        result = build_history(chosen)
        self.assertEqual(result['entries'], 1)
        self.assertNotIn('PRIVATE-TITLE', (chosen/'index.html').read_text())
        self.assertEqual(own.read_bytes(), before)

    def test_feedback_refresh_is_escaped_and_not_duplicated(self):
        path = write_log(self.root/'bean/cup/logs/one.jsonl', session('<script>bean</script>'))
        record = path.parent.parent/'record.md'
        record.write_text('<script>feedback</script>初次评价')
        build_history(self.root)
        report = path.parent/'reports/one.html'
        self.assertNotIn('<script>', report.read_text())
        self.assertIn('&lt;script&gt;feedback', report.read_text())
        record.write_text('温凉后反馈')
        build_history(self.root)
        self.assertIn('温凉后反馈', report.read_text())
        self.assertNotIn('初次评价', report.read_text())
        self.assertEqual(report.read_text().count('<details'), 1)

    def test_same_basename_in_two_cups_not_lost(self):
        write_log(self.root/'cup1/logs/one.jsonl', session('one'))
        write_log(self.root/'cup2/logs/one.jsonl', session('two'))
        self.assertEqual(build_history(self.root)['entries'], 2)

    def test_report_failure_keeps_attempt_and_error(self):
        write_log(self.root/'fail.jsonl', session())
        with patch('xbloom_bridge.history.generate_report', side_effect=OSError('synthetic disk failure')):
            result = build_history(self.root)
        self.assertEqual(result['entries'], 1)
        self.assertIn('synthetic disk failure', str(result['warnings']))
        self.assertIn('fail.jsonl', (self.root/'index.html').read_text())

    def test_broken_tail_remains_visible(self):
        p = write_log(self.root/'tail.jsonl', session())
        p.write_text(p.read_text()+'{broken')
        result = build_history(self.root)
        self.assertEqual(result['entries'], 1)
        self.assertTrue(result['warnings'])


class TimingTests(unittest.TestCase):
    def test_ready_fallback_names_its_source_and_preserves_receive_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write_log(Path(tmp)/'ready.jsonl', session()+[
                event(20, code=40510), event(30, coffee_g=25), event(80, state='ready')])
            data = build_report(p)
            self.assertEqual(data['candidate'], 60)
            self.assertEqual(data['candidate_source'], 'ready')
            self.assertIn('ready', str(data['warnings']))
            self.assertIn('屏显计时 / 最后一滴', render_svg(data))

    def test_40512_preferred_and_no_end_evidence_stays_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'candidate.jsonl'
            write_log(p, session()+[event(10, code=40510), event(50, code=40512), event(55, state='ready')])
            self.assertEqual(build_report(p)['candidate_source'], '40512')
            self.assertEqual(build_report(p)['candidate'], 40)
            write_log(p, session()+[event(10, code=40510), event(50, coffee_g=200)])
            self.assertIsNone(build_report(p)['candidate'])


if __name__ == '__main__':
    unittest.main()
