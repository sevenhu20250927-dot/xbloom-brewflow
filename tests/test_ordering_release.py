"""Offline checks with an empty database and synthetic bean labels."""
import copy
import json
from pathlib import Path
import struct
import tempfile
import unittest
from uuid import uuid4

from ordering import recommendations
from ordering.store import ProductError, Store, daily_menu
from scripts.xbloom_bridge import protocol

ROOT = Path(__file__).resolve().parents[1]


class OrderTests(unittest.TestCase):
    def test_order_lifecycle_and_retries(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "test.sqlite3")
            self.assertTrue(all(not rows for rows in store.state().values()))
            with store._connection(write=True) as db:
                db.execute("INSERT INTO tasters VALUES (1,'guest')")
                db.execute("INSERT INTO menu_beans VALUES (1,'A','R','','','','','','45')")
            payload = dict(person_id=1, bean_id=1, mode="grind_own", note="", request_id=uuid4().hex)
            first = store.create_order(payload)
            self.assertEqual(first, store.create_order(payload))
            self.assertEqual(first, store.create_order(dict(payload,request_id=uuid4().hex)))
            def expected(order):
                return {k:order[k] for k in ('bean_id','person_id','mode','note','status')}
            def act(action,order):
                return store.transition(order['id'],dict(expected=expected(order),request_id=uuid4().hex),action)
            updated = store.update_order(first['id'],dict(payload,request_id=uuid4().hex,note='B',expected=expected(first)))
            with self.assertRaises(ProductError):
                act('accept',first)
            accepted = act('accept',updated)
            self.assertEqual(accepted['status'],'accepted')
            self.assertEqual(act('finish',accepted)['status'],'fulfilled')
            next_order=store.create_order(dict(payload,request_id=uuid4().hex))
            self.assertEqual(act('delete',act('cancel',next_order))['status'],'deleted')
            self.assertEqual(len(store.state()['orders']),1)
            self.assertEqual(store.state()['beans'][0]['net_weight'],45)

    def test_menu_and_recommendation_evidence(self):
        beans=[dict(id=i,name=f'Sample {i}',roaster=f'Test {i}',net_weight=30 if i else 10) for i in range(7)]
        self.assertEqual(len(daily_menu(beans)),5)
        self.assertNotIn(0,[b['id'] for b in daily_menu(beans)])
        state=dict(beans=beans,people=[dict(id=1,name='guest')],preferences=[])
        ctx=recommendations.build_context(state,person_id=1)
        def item(i):
            return dict(bean_id=i,reason='Mock',story='Mock',citations=[dict(source_id=f'bean:{i}',quote=f'Sample {i}')])
        doc=dict(person_id=1,items=[item(i) for i in (2,3,4)])
        self.assertEqual(len(recommendations.validate_output(json.dumps(doc),ctx)['items']),3)
        doc['items'][0]['citations'][0]['quote']='unknown source'
        with self.assertRaises(ValueError):
            recommendations.validate_output(json.dumps(doc),ctx)


class PreGroundContract(unittest.TestCase):
    def test_bypass_off_and_on_with_both_grinding_modes(self):
        recipe=json.loads((ROOT/'examples/bypass.recipe.json').read_text())
        for with_bypass in (True,False):
            for preground in (True,False):
                with self.subTest(bypass=with_bypass,preground=preground):
                    payload=copy.deepcopy(recipe)
                    if not with_bypass:
                        del payload['bypassMl'],payload['bypassTempC']
                    if preground:
                        r=payload['recipe']
                        del r['grinderSize'],r['rpm']
                        r['grindEnabled']=False
                    frames=protocol.build_recipe_frames(payload)
                    self.assertEqual([struct.unpack_from('<H',frame,3)[0] for _,frame in frames],
                                     [8102,8104,8004 if preground else 8001])
                    self.assertEqual(struct.unpack_from('<f',frames[0][1],10)[0],15 if with_bypass else 0)
                    if preground:
                        self.assertEqual(frames[-1][0],'recipe_no_grind')
                        self.assertEqual(frames[-1][1][-4],0xfe)
                        r['grinderSize']=51
                        with self.assertRaises(protocol.ProtocolError):
                            protocol.build_recipe_frames(payload)
