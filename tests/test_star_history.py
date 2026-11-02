import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from app import database, payments, star_history, vpn_alerts


class StarHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.path=Path(self.tmp.name)/'test.sqlite3'
        database.initialize(self.path); database.register_user(1,self.path); database.register_user(2,self.path)
        self.order=payments.create_order(1,'days7',50,path=self.path,now=1000)['order_id']
    def tearDown(self): self.tmp.cleanup()
    def transaction(self, **kwargs):
        return dict({'id':'charge','direction':'incoming','user_id':1,'order_id':self.order,'amount':50,'date':1001},**kwargs)
    def rows(self):
        with closing(sqlite3.connect(self.path)) as db: return db.execute('SELECT transaction_id,direction,status FROM star_history ORDER BY direction').fetchall()
    def test_valid_restart_and_duplicates(self):
        t=self.transaction(); star_history.observe(t,path=self.path,now=1002); database.initialize(self.path)
        star_history.observe(t,path=self.path,now=1003); star_history.finalize(path=self.path,now=1004)
        first=database.get_subscription(1,self.path)
        self.assertEqual(first['expires_at'],1004+7*86400)
        star_history.observe(t,path=self.path); star_history.finalize(path=self.path,now=2000)
        self.assertEqual(database.get_subscription(1,self.path),first)
    def test_ambiguous_items_are_reviewed(self):
        for i,changes in enumerate(({'order_id':None},{'order_id':'unknown'},{'amount':51},{'user_id':2})):
            star_history.observe(self.transaction(id='bad'+str(i),**changes),path=self.path,now=1000)
        star_history.finalize(path=self.path,now=1001)
        self.assertTrue(all(r[2]=='review' for r in self.rows()))
        self.assertIsNone(database.get_subscription(1,self.path))
        self.assertTrue(vpn_alerts.due(path=self.path,now=1001))
    def test_payment_and_refund_same_id(self):
        star_history.observe(self.transaction(),path=self.path,now=1000)
        star_history.observe(self.transaction(direction='outgoing',order_id=None),path=self.path,now=1000)
        star_history.finalize(path=self.path,now=1001)
        self.assertEqual(self.rows(), [('charge','incoming','review'),('charge','outgoing','refund_review')])
        self.assertIsNone(database.get_subscription(1,self.path))
    def test_conflicting_repeat_and_database_failure(self):
        star_history.observe(self.transaction(),path=self.path,now=1000)
        self.assertEqual(star_history.observe(self.transaction(amount=51),path=self.path,now=1001),'review')
        star_history.finalize(path=self.path,now=1002)
        self.assertIsNone(database.get_subscription(1,self.path))
        with self.assertRaises(sqlite3.Error): star_history.observe(self.transaction(),path=self.path/'invalid')


if __name__ == '__main__': unittest.main()
