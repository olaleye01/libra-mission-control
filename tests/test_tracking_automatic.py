"""Automatic monitoring decisions and writes, using only synthetic carrier pages."""
import copy
import datetime as dt
import json
import threading
import time
import uuid
from zoneinfo import ZoneInfo
import unittest
from unittest.mock import patch

from test_application import HttpFixture, report
from test_tracking import page
from records import records
from tracking import Tracking, config, next_slot
from msc_browser import CollectorError


class AutomaticTrackingTests(HttpFixture):
    def setUp(self):
        super().setUp()
        self.owner()
        self.app=self.httpd.app
        self.tracking=self.app.tracking
        self.tracking.collector=lambda bl:page(bl)
        status,result,_=self.call('POST','/api/shipments',dict(client_id=1,command_id=uuid.uuid4().hex,
            reason='Synthetic automatic tracking job',changes=dict(bl='MSCDEMO12345',container_count=1,liner='MSC')))
        self.assertEqual(status,200,result)
        self.shipment=result['shipment']
        self.base='/api/shipments/'+str(self.shipment['id'])

    def detail(self):
        return self.call('GET',self.base)[1]['shipment']

    def state(self):
        return self.call('GET',self.base+'/tracking')[1]['tracking']

    def tick(self, expected=True):
        self.assertEqual(self.tracking.tick(),expected)
        if expected:
            self.tracking.thread.join(5)
            self.assertFalse(self.tracking.thread.is_alive())
        return self.state()

    def make_due(self):
        with self.app.store.connect() as con:
            row=con.execute('SELECT data FROM tracking_configs WHERE shipment_id=?',(self.shipment['id'],)).fetchone()
            data=json.loads(row[0]);data['next_due']=0
            con.execute('UPDATE tracking_configs SET data=? WHERE shipment_id=?',(json.dumps(data),self.shipment['id']))
            con.execute('UPDATE tracking_checks SET started_at=started_at-31')

    def update(self,changes):
        record=self.detail()
        status,result,_=self.call('POST',self.base+'/update',dict(command_id=uuid.uuid4().hex,
            revision=record['revision'],reason='Explicit owner correction',changes=changes))
        self.assertEqual(status,200,result)
        return result['shipment']

    def test_automatic_enrolment_discovery_updates_and_returns_stop_without_chore(self):
        self.assertEqual(self.state()['config']['status'],'not_enabled')
        state=self.tick()
        self.assertEqual(state['config']['status'],'finished')
        self.assertEqual(state['config']['destination'],'Apapa, NG')
        self.assertIsNone(state['next_due'])
        self.assertEqual(state['latest']['review']['decision'],'automatic')
        self.assertIn('discharge',state['latest']['review']['fields'])
        job=self.detail()
        self.assertEqual(job['dates']['discharge'],'2024-06-04')
        self.assertEqual(job['operation']['closure']['empty_returns']['date'],'2024-06-13')
        self.assertIsNone(job['dates']['warehouse'])
        self.assertFalse(job['operation']['completed'])
        self.assertEqual(job['state'],'In clearing')
        restarted=Tracking(self.app);restarted.collector=lambda bl:self.fail('Finished tracking was queried again')
        self.assertFalse(restarted.tick())

    def test_source_owned_eta_updates_but_owner_change_and_back_is_retained(self):
        self.tracking.collector=lambda bl:page(bl,returned=False,eta='06/11/2026')
        first=self.tick()
        self.assertEqual(self.detail()['dates']['eta'],'2026-11-06')
        self.make_due()
        self.tracking.collector=lambda bl:page(bl,returned=False,eta='07/11/2026')
        self.tick()
        self.assertEqual(self.detail()['dates']['eta'],'2026-11-07')
        self.update({'dates':{'eta':'2026-11-08'}})
        self.update({'dates':{'eta':'2026-11-07'}})
        self.make_due()
        self.tracking.collector=lambda bl:page(bl,returned=False,eta='09/11/2026')
        latest=self.tick()
        self.assertEqual(self.detail()['dates']['eta'],'2026-11-07')
        self.assertTrue(any(x['field']=='eta' for x in latest['attention']))
        self.assertNotEqual(first['latest']['id'],latest['latest']['id'])

    def test_owner_cleared_blank_is_not_refilled_automatically(self):
        self.update({'dates':{'eta':'2026-11-07'}})
        self.update({'dates':{'eta':None}})
        self.tracking.collector=lambda bl:page(bl,returned=False,eta='09/11/2026')
        state=self.tick()
        self.assertIsNone(self.detail()['dates']['eta'])
        self.assertTrue(any(x['field']=='eta' for x in state['attention']))
        self.assertEqual(self.detail()['dates']['discharge'],'2024-06-04')

    def test_historical_test_jobs_are_excluded_from_automatic_enrolment(self):
        record=self.detail()
        historical=copy.deepcopy(record)
        historical['batch_id']='synthetic-history'
        historical['operation']['reconciled']=False
        self.assertFalse(self.tracking.eligibility(historical)[0])
        with patch('tracking.records',return_value=[historical]):
            self.assertFalse(self.tracking.tick())
        with self.app.store.connect() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM tracking_configs').fetchone()[0],0)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM tracking_checks').fetchone()[0],0)
        historical['operation']['reconciled']=True
        self.assertTrue(self.tracking.eligibility(historical)[0])

    def test_reconciled_import_eta_is_source_owned_and_raw_snapshot_is_unchanged(self):
        status,result,_=self.preview(report({3:'MSCIMPORT12345',6:'06-Nov-26',8:'1',26:''}))
        self.assertEqual(status,200,result)
        batch=result['batch']['id']
        self.assertEqual(self.call('POST','/api/imports/'+batch+'/apply',{'confirm_test_import':True})[0],200)
        imported=next(r for r in self.call('GET','/api/shipments')[1]['shipments'] if r['bl']=='MSCIMPORT12345')
        self.shipment=imported
        self.base='/api/shipments/'+str(imported['id'])
        before=self.detail()['source_snapshot']
        self.update({'reconciled':True})
        self.tracking.allowed_bls={'MSCIMPORT12345'}
        self.tracking.collector=lambda bl:page(bl,returned=False,eta='07/11/2026')
        state=self.tick()
        self.assertEqual(self.detail()['dates']['eta'],'2026-11-07')
        self.assertEqual(self.detail()['source_snapshot'],before)
        self.assertFalse(any(c['field']=='eta' for c in state['attention']))

    def test_reason_free_retry_is_idempotent_and_does_not_need_setup(self):
        request={'command_id':uuid.uuid4().hex}
        first=self.call('POST',self.base+'/tracking/check',request)
        self.assertEqual(first[0],200,first[1])
        self.tracking.thread.join(5)
        second=self.call('POST',self.base+'/tracking/check',request)
        self.assertEqual(second[0],200,second[1])
        self.assertEqual(second[1],first[1])
        with self.app.store.connect() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM tracking_checks').fetchone()[0],1)

    def test_global_claim_prevents_two_workers_collecting_same_job(self):
        gate=threading.Event()
        calls=[]
        def collector(bl):
            calls.append(bl);gate.wait(3);return page(bl)
        self.tracking.collector=collector
        self.assertTrue(self.tracking.tick())
        other=Tracking(self.app);other.collector=lambda bl:self.fail('A second worker queried MSC')
        try:self.assertFalse(other.tick())
        finally:gate.set();self.tracking.thread.join(5)
        self.assertEqual(calls,['MSCDEMO12345'])

    def test_count_mismatch_records_exception_without_inventing_dates(self):
        self.update({'container_count':4})
        state=self.tick()
        self.assertEqual(state['config']['status'],'active')
        self.assertTrue(any(x['field']=='container_count' for x in state['attention']))
        self.assertIsNone(self.detail()['dates']['discharge'])
        self.assertIsNone(self.detail()['operation']['closure']['empty_returns']['date'])

    def test_failure_backoff_and_last_success_survives_many_failures(self):
        self.tracking.collector=lambda bl:page(bl,returned=False)
        first=self.tick()
        success=first['latest']['id']
        self.make_due()
        self.tracking.collector=lambda bl:(_ for _ in ()).throw(CollectorError('Temporary carrier failure'))
        state=self.tick()
        self.assertGreater(state['next_due'],time.time()+14*60)
        self.assertEqual(state['latest']['id'],success)
        self.assertFalse(self.tracking.tick())
        with self.app.store.connect() as con:
            now=time.time()
            for n in range(22):
                con.execute("INSERT INTO tracking_checks(id,shipment_id,config_revision,started_at,ended_at,status,error) VALUES(?,?,1,?,?,'failed','synthetic failure')",
                            (uuid.uuid4().hex,self.shipment['id'],now+n,now+n))
        self.assertEqual(self.state()['latest']['id'],success)
        restarted=Tracking(self.app)
        self.assertFalse(restarted.tick())

    def test_scoped_summary_is_read_only_and_reports_failure_without_opening_job(self):
        self.tracking.collector=lambda bl:(_ for _ in ()).throw(CollectorError('Synthetic carrier block'))
        self.tick()
        with self.app.store.connect() as con:scope=records(con)
        summary=self.tracking.summary(scope)
        self.assertEqual(summary['monitored_count'],1)
        self.assertEqual(summary['attention_count'],1)
        self.assertEqual(summary['attention'][0]['shipment_id'],self.shipment['id'])
        self.assertEqual(self.tracking.summary([])['attention_count'],0)
        with self.app.store.connect() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM tracking_checks').fetchone()[0],1)

    def test_legacy_finished_monitor_is_preserved_when_upgrading_automation(self):
        self.tick()
        with self.app.store.connect() as con:
            row=con.execute('SELECT data FROM tracking_configs WHERE shipment_id=?',(self.shipment['id'],)).fetchone()
            legacy=json.loads(row[0]);legacy.pop('automatic');legacy.pop('expected_count')
            con.execute('UPDATE tracking_configs SET data=? WHERE shipment_id=?',(json.dumps(legacy),self.shipment['id']))
        self.tracking.collector=lambda bl:self.fail('Legacy finished shipment was re-queried')
        state=self.tick(expected=False)
        self.assertEqual(state['config']['status'],'finished')
        self.assertIsNone(state['next_due'])


class ScheduleBoundaryTests(unittest.TestCase):
    def test_eight_and_sixteen_lagos_slots_survive_restart(self):
        zone=ZoneInfo('Africa/Lagos')
        for stamp,expected in [('2026-10-31T07:59:00','2026-10-31T08:00:00'),
                               ('2026-10-31T08:00:00','2026-10-31T16:00:00'),
                               ('2026-10-31T16:00:00','2026-11-01T08:00:00')]:
            current=dt.datetime.fromisoformat(stamp).replace(tzinfo=zone).timestamp()
            target=dt.datetime.fromisoformat(expected).replace(tzinfo=zone).timestamp()
            self.assertEqual(next_slot(current),target)
