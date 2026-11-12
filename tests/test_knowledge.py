"""Cold-start data integrity checks; files only, no model, database or device."""
import hashlib
import json
import math
from pathlib import Path
import re
import unittest
from urllib.parse import unquote

PACKAGE = Path(__file__).resolve().parents[1]
KNOWLEDGE = PACKAGE / 'knowledge'


def read(path):
    return json.loads(path.read_text())


class KnowledgeIntegrityTests(unittest.TestCase):
    def test_source_manifest_is_complete_and_bytes_match(self):
        manifest = read(KNOWLEDGE / 'catalog.json')
        paths = [item['path'] for item in manifest['sources']]
        self.assertEqual(len(paths), len(set(paths)))
        for item in manifest['sources']:
            path = (PACKAGE / item['path']).resolve()
            self.assertTrue(path.is_relative_to(PACKAGE))
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                             item['published_sha256'], item['path'])
        self.assertEqual(len(list((KNOWLEDGE / 'source-snapshot/brew-data-package/runs').glob('*.json'))), 25)

    def test_references_work_without_the_authors_workspace(self):
        for path in PACKAGE.rglob('*.md'):
            for href in re.findall(r'\]\(([^)\n]+)\)', path.read_text()):
                if href.startswith(('http:', 'https:', 'mailto:', '#')):
                    continue
                target = (path.parent / unquote(href.split('#', 1)[0])).resolve()
                self.assertTrue(target.is_relative_to(PACKAGE), (path, href))
                self.assertTrue(target.exists(), (path, href))

    def test_redtail_coupled_changes_and_missing_feedback_are_preserved(self):
        root = KNOWLEDGE / 'source-snapshot/brew-data-package/runs'
        a = read(root / '20261030-143522-completed_no_signal.json')
        b = read(root / '20261104-151622-completed_no_signal.json')
        c = read(root / '20261105-214927-completed_no_signal.json')
        d = read(root / '20261106-141646-completed.json')
        self.assertEqual([x['recipe']['recipe']['grinderSize'] for x in (a,b,c,d)], [50,52,51,51])
        self.assertNotEqual(a['recipe']['recipe']['pours'][0]['temperature'], b['recipe']['recipe']['pours'][0]['temperature'])
        self.assertNotEqual(a['recipe']['recipe']['pours'][0]['pausing'], b['recipe']['recipe']['pours'][0]['pausing'])
        self.assertEqual((c['recipe']['doseGrams'], d['recipe']['doseGrams']), (15,16))
        self.assertEqual((c['recipe']['recipe']['grandWater'], d['recipe']['recipe']['grandWater']), (240,256))
        self.assertIsNone(d['taste_note'])

    def test_failed_attempts_are_not_promoted_to_successful_bypass_cups(self):
        files = list((KNOWLEDGE / 'log').rglob('20261110T05*.json'))
        self.assertEqual(len(files), 3)
        for path in files:
            data = read(path)
            events = data['events']
            starts = [e for e in events if e.get('kind') == 'tx_intent' and e.get('label') == 'start_commit']
            if '054219Z' in path.name:
                self.assertEqual(len(starts), 1)
                recipe = next(e for e in events if e['kind'] == 'session')['recipe']
                self.assertEqual((recipe['recipe']['grandWater'], recipe['bypassMl']), (210,15))
                self.assertEqual(next(e for e in events if e['kind'] == 'observation_ended')['completion'], 'unconfirmed')
                weights = [w[4] for w in data['weights'] if w[4] is not None]
                self.assertTrue(any(math.isclose(w,188.11,abs_tol=.02) for w in weights))
                self.assertTrue(any(math.isclose(w,181.73,abs_tol=.02) for w in weights))
            else:
                self.assertFalse(starts)
                self.assertTrue(any(e['kind'] == 'error' for e in events))
                self.assertFalse(data['weights'])

    def test_sqlite_records_and_independent_tasters_remain_linked(self):
        manifest = read(KNOWLEDGE / 'catalog.json')
        records = [read(PACKAGE / x['path']) for x in manifest['sources'] if x['kind']=='sqlite-record']
        brews = {r['source_record_id']:r for r in records if 'source_record_id' in r}
        self.assertEqual(len(brews), 26)
        self.assertEqual(sum(len(r['personal_tastings']) for r in records), 8)
        self.assertEqual({x['person_id'] for x in brews[20]['personal_tastings']}, {1,2})
        self.assertEqual(brews[21]['record']['technique']['dose'], '')
        self.assertEqual(brews[24]['record']['tasting']['score'], '')
        self.assertFalse(brews[24]['personal_tastings'])
        self.assertEqual(brews[28]['record']['technique']['dose'], '15g')

    def test_source_data_does_not_depend_on_device_identifiers(self):
        for path in KNOWLEDGE.rglob('*'):
            if not path.is_file():
                continue
            text = path.read_text()
            self.assertNotIn('/Users/', text, path)
            self.assertNotIn('3BFA159E-2AAA-9696-EA68-4C0FF967683E', text, path)
            self.assertNotRegex(text, r'J15[A-Z0-9]{8,}')


if __name__ == '__main__':
    unittest.main()
