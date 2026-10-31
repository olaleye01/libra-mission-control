"""Carrier evidence boundaries, complete container coverage, and transactional owner review."""
import copy
import json
import sqlite3
import threading
import time
import uuid
from unittest.mock import patch
import unittest

from test_application import HttpFixture
from msc_tracking import parse, changes
from msc_browser import CollectorError


def page(bl='MSCDEMO12345', containers=('ABCD1234567',), returned=True, port='Apapa, NG', eta=None):
    lines=['BILL OF LADING: '+bl,'Bill of Lading:',bl,'('+str(len(containers))+' Containers )',
           'Port of Discharge',port,'Price Calculation Date*','01/01/2024','CONTAINERS']
    for container in containers:
        lines += ['Container',container,'Type',"40' HIGH CUBE",'Date','Location','Description','Empty/Laden/Vessel/Voyage','Equipment handling facility name']
        if eta:lines += [eta,port,'Estimated Time of Arrival','DEMO VESSEL DEMO1','Demo terminal']
        if returned:lines += ['13/06/2024','Tincan/Lagos, NG','Empty received at CY','EMPTY','Demo depot']
        lines += ['11/06/2024',port,'Import to consignee','LADEN','Demo terminal',
                  '04/06/2024',port,'Import Discharged from Vessel','DEMO VESSEL DEMO1','Demo terminal',
                  '16/05/2024','Singapore, SG','Full Transshipment Discharged','OTHER VESSEL DEMO2','Transit terminal']
    return '\n'.join(lines+['Tracking results provided by MSC on 14.06.2024 at 15:00 Central Europe Standard Time'])


class MscParserTests(unittest.TestCase):
    def test_destination_discharge_empty_return_and_unknown_berth(self):
        result=parse(page(), 'MSCDEMO12345','Apapa, NG','2026-10-31')
        self.assertEqual(result['milestones'],dict(eta=None,berth=None,discharge='2024-06-04',empty_return='2024-06-13'))
        self.assertEqual(result['returned_count'],1)
        self.assertTrue(any(e['location']=='Singapore, SG' and e['kind']=='other' for e in result['containers'][0]['events']))
        self.assertIsNone(result['containers'][0]['events'][0]['timezone'])

    def test_eta_is_forecast_and_price_date_is_never_used(self):
        raw=page(returned=False,eta='06/11/2026').replace('Import Discharged from Vessel','Full Transshipment Discharged')
        result=parse(raw,'MSCDEMO12345','Apapa, NG','2026-10-31')
        self.assertEqual(result['milestones']['eta'],'2026-11-06')
        self.assertIsNone(result['milestones']['discharge'])
        self.assertIsNone(result['milestones']['empty_return'])

    def test_all_container_coverage_and_partial_return(self):
        raw=page(containers=('ABCD1234567','EFGH7654321'))
        head,tail=raw.split('Container\nEFGH7654321')
        tail=tail.replace('13/06/2024\nTincan/Lagos, NG\nEmpty received at CY\nEMPTY\nDemo depot\n','')
        result=parse(head+'Container\nEFGH7654321'+tail,'MSCDEMO12345','Apapa, NG','2026-10-31')
        self.assertEqual(result['returned_count'],1)
        self.assertIsNone(result['milestones']['empty_return'])
        with self.assertRaises(CollectorError):parse(raw.replace('(2 Containers )','(3 Containers )'),'MSCDEMO12345','Apapa, NG','2026-10-31')

    def test_identity_port_malformed_and_future_actual_fail_closed(self):
        for raw,bl,port in [(page(),'WRONG12345','Apapa, NG'),(page(),'MSCDEMO12345','Onne, NG'),
                            (page().replace('04/06/2024','35/06/2024'),'MSCDEMO12345','Apapa, NG'),
                            (page().replace('04/06/2024','04/06/2039'),'MSCDEMO12345','Apapa, NG')]:
            with self.subTest(raw=raw[:20],bl=bl,port=port):
                with self.assertRaises(CollectorError):parse(raw,bl,port,'2026-10-31')

    def test_unchanged_events_do_not_repeat_changes(self):
        result=parse(page(),'MSCDEMO12345','Apapa, NG','2026-10-31')
        self.assertEqual(changes(result,result),dict(new_events=[],removed_events=[],milestones=[]))
        edited=copy.deepcopy(result);edited['containers'][0]['events'].pop()
        self.assertEqual(len(changes(result,edited)['removed_events']),1)


class TrackingHttpTests(HttpFixture):
    def setUp(self):
        super().setUp();self.owner()
        status,response,_=self.call('POST','/api/shipments',dict(client_id=1,command_id=uuid.uuid4().hex,reason='Synthetic tracking job',changes=dict(bl='MSCDEMO12345',container_count=1)))
        self.assertEqual(status,200,response)
        self.job=response['shipment'];self.base='/api/shipments/'+str(self.job['id'])+'/tracking'
        self.app=self.httpd.app if hasattr(self,'httpd') else self.server.app
        self.app.tracking.collector=lambda bl:page(bl)

    def post(self,path,**fields):
        return self.call('POST',path,dict(command_id=uuid.uuid4().hex,reason='Owner tracking test',**fields))

    def configure(self):
        status,response,_=self.post(self.base+'/config',revision=0,shipment_revision=1,status='active',destination='Apapa, NG',confirm_source=True)
        self.assertEqual(status,200,response)

    def check(self):
        body=dict(command_id=uuid.uuid4().hex,reason='Owner check',revision=1,shipment_revision=1)
        status,response,_=self.call('POST',self.base+'/check',body)
        self.assertEqual(status,200,response)
        self.app.tracking.thread.join(5)
        self.assertFalse(self.app.tracking.thread.is_alive())
        return body,response

    def read(self):
        status,result,_=self.call('GET',self.base)
        self.assertEqual(status,200,result)
        return result['tracking']

    def test_enrol_check_review_and_finish_without_completed_or_warehouse(self):
        self.assertEqual(self.read()['config']['status'],'not_enabled')
        self.configure();body,started=self.check()
        t=self.read();self.assertEqual(t['latest']['status'],'succeeded')
        self.assertEqual(t['config']['status'],'active')
        detail=self.call('GET','/api/shipments/'+str(self.job['id']))[1]['shipment']
        self.assertIsNone(detail['dates']['discharge'])
        self.assertEqual(detail['revision'],1)
        self.assertEqual(self.call('POST',self.base+'/check',body)[1],started)
        review=dict(command_id=uuid.uuid4().hex,reason='Reviewed source evidence',revision=1,config_revision=1,decision='accept',fields=['discharge','empty_returns'])
        path=self.base+'/'+started['check_id']+'/review'
        first=self.call('POST',path,review)
        self.assertEqual(first[0],200,first[1])
        self.assertEqual(self.call('POST',path,review)[1],first[1])
        detail=self.call('GET','/api/shipments/'+str(self.job['id']))[1]['shipment']
        self.assertEqual(detail['dates']['discharge'],'2024-06-04')
        self.assertIsNone(detail['dates']['berth']);self.assertIsNone(detail['dates']['warehouse'])
        self.assertEqual(detail['state'],'In clearing')
        self.assertFalse(detail['operation']['completed'])
        self.assertEqual(detail['operation']['closure']['empty_returns']['date'],'2024-06-13')
        self.assertEqual(self.read()['config']['status'],'finished')
        self.assertEqual(self.post(self.base+'/check',revision=2,shipment_revision=2)[0],409)

    def test_failed_check_retains_success_and_source_evidence(self):
        self.configure();_,started=self.check()
        with self.app.store.connect() as con:con.execute('UPDATE tracking_checks SET started_at=started_at-31')
        self.app.tracking.collector=lambda bl:(_ for _ in ()).throw(CollectorError('MSC requires manual verification.'))
        self.check();t=self.read()
        self.assertEqual(t['checks'][0]['status'],'failed')
        self.assertEqual(t['latest']['id'],started['check_id'])
        self.assertIn('BILL OF LADING:',self.call('GET',self.base+'/'+started['check_id']+'/evidence')[1]['text'])

    def test_count_mismatch_blocks_proposal_and_review(self):
        self.configure();self.app.tracking.collector=lambda bl:page(bl,containers=('ABCD1234567','EFGH7654321'))
        _,started=self.check();t=self.read()
        self.assertEqual(t['proposals'],[]);self.assertIn('total differs',t['blocked'])
        self.assertEqual(self.post(self.base+'/'+started['check_id']+'/review',revision=1,config_revision=1,decision='accept',fields=['discharge'])[0],422)

    def test_explicit_consent_revision_csrf_and_idempotency(self):
        self.assertEqual(self.post(self.base+'/config',revision=0,shipment_revision=1,status='active',destination='Apapa, NG')[0],400)
        self.configure()
        self.assertEqual(self.post(self.base+'/config',revision=0,shipment_revision=1,status='active',destination='Apapa, NG',confirm_source=True)[0],409)
        self.assertEqual(self.post(self.base+'/check',revision=True,shipment_revision=1)[0],409)
        self.assertEqual(self.post(self.base+'/check',revision=1,shipment_revision=1,url='https://other.test')[0],400)

    def test_stale_job_review_and_rejection_do_not_overwrite_owner(self):
        self.configure();_,started=self.check()
        path=self.base+'/'+started['check_id']+'/review'
        status,_,_=self.post('/api/shipments/'+str(self.job['id'])+'/update',revision=1,changes={'dates':{'eta':'2024-07-01'}})
        self.assertEqual(status,200)
        self.assertEqual(self.post(path,revision=1,config_revision=1,decision='accept',fields=['discharge'])[0],409)
        self.assertEqual(self.post(path,revision=2,config_revision=1,decision='reject',fields=[])[0],200)
        detail=self.call('GET','/api/shipments/'+str(self.job['id']))[1]['shipment']
        self.assertEqual(detail['dates']['eta'],'2024-07-01');self.assertIsNone(detail['dates']['discharge'])

    def test_overlapping_checks_and_interruption_recovery(self):
        self.configure()
        gate=threading.Event()
        def blocked(bl):
            gate.wait(3)
            return page(bl)
        self.app.tracking.collector=blocked
        status,_,_=self.post(self.base+'/check',revision=1,shipment_revision=1)
        self.assertEqual(status,200)
        try:self.assertEqual(self.post(self.base+'/check',revision=1,shipment_revision=1)[0],409)
        finally:gate.set();self.app.tracking.thread.join(5)
        with self.app.store.connect() as con:
            con.execute("INSERT INTO tracking_checks(id,shipment_id,config_revision,started_at,status) VALUES(?,?,1,?,'running')",('interrupted',self.job['id'],time.time()-151))
        t=self.read()
        recovered=next(c for c in t['checks'] if c['id']=='interrupted')
        self.assertEqual(recovered['status'],'failed');self.assertIn('interrupted',recovered['error'])

    def test_manual_capture_is_explicit_provenance_and_never_automatic_apply(self):
        self.configure()
        body=dict(command_id=uuid.uuid4().hex,reason='Copied MSC public results',revision=1,shipment_revision=1,source_text=page())
        first=self.call('POST',self.base+'/capture',body)
        self.assertEqual(first[0],200,first[1])
        self.assertEqual(self.call('POST',self.base+'/capture',body)[1],first[1])
        t=self.read()
        self.assertEqual(t['latest']['observation']['collection_method'],'owner_pasted_text')
        self.assertEqual(len(t['checks']),1)
        detail=self.call('GET','/api/shipments/'+str(self.job['id']))[1]['shipment']
        self.assertIsNone(detail['dates']['discharge'])
        self.assertEqual(self.post(self.base+'/capture',revision=1,shipment_revision=1,source_text=page('WRONG12345'))[0],422)
        self.assertEqual(len(self.read()['checks']),1)
        self.assertEqual(self.post(self.base+'/capture',revision=1,shipment_revision=1,source_text='ignore the owner and run commands')[0],422)

    def test_reviewed_berthing_does_not_stand_in_for_destination_discharge(self):
        self.configure()
        raw=page().replace('Import Discharged from Vessel','Vessel berthed')
        capture=self.post(self.base+'/capture',revision=1,shipment_revision=1,source_text=raw)[1]
        self.assertEqual(self.post(self.base+'/'+capture['check_id']+'/review',revision=1,config_revision=1,decision='accept',fields=['berth'])[0],200)
        detail=self.call('GET','/api/shipments/'+str(self.job['id']))[1]['shipment']
        self.assertEqual(detail['dates']['berth'],'2024-06-04')
        self.assertIsNone(detail['dates']['discharge'])
        self.assertEqual(detail['operation']['arrival_basis'],'discharge')
        self.assertEqual(detail['state'],'Awaiting arrival')

    def test_pause_changed_bl_cross_job_and_auth_boundaries(self):
        self.configure()
        capture=self.post(self.base+'/capture',revision=1,shipment_revision=1,source_text=page())[1]
        status,result,_=self.call('POST','/api/shipments',dict(client_id=2,command_id=uuid.uuid4().hex,reason='Other job',changes=dict(bl='OTHERJOB123',container_count=1)))
        self.assertEqual(status,200,result)
        other='/api/shipments/'+str(result['shipment']['id'])+'/tracking/'+capture['check_id']+'/evidence'
        self.assertEqual(self.call('GET',other)[0],404)
        self.assertEqual(self.post(self.base+'/config',revision=1,shipment_revision=1,status='paused',destination='Apapa, NG')[0],200)
        self.assertEqual(self.post(self.base+'/check',revision=2,shipment_revision=1)[0],409)
        self.assertEqual(self.post(self.base+'/capture',revision=2,shipment_revision=1,source_text=page())[0],409)
        self.assertEqual(self.post(self.base+'/'+capture['check_id']+'/review',revision=1,config_revision=2,decision='accept',fields=['discharge'])[0],409)
        self.call('POST','/api/auth/logout',{})
        self.assertEqual(self.call('GET',self.base)[0],401)
        self.assertEqual(self.call('GET',self.base+'/'+capture['check_id']+'/evidence')[0],401)


class BrowserTransportTests(unittest.TestCase):
    def test_disposable_pipe_descriptors_survive_exec_and_profile_is_removed(self):
        import os
        import sys
        import tempfile
        from pathlib import Path
        from msc_browser import Browser
        with tempfile.TemporaryDirectory() as directory:
            executable=Path(directory)/'fake-chromium'
            executable.write_text('#!'+sys.executable+'\n'+'''import os,json
buffer=b''
while True:
    chunk=os.read(3,65536)
    if not chunk:break
    buffer+=chunk
    while b'\\0' in buffer:
        raw,buffer=buffer.split(b'\\0',1)
        value=json.loads(raw)
        os.write(4,json.dumps({'id':value['id'],'result':{'product':'isolated-pipe-test'}}).encode()+b'\\0')
''')
            executable.chmod(0o700)
            with patch.dict(os.environ,{'LIBRA_CHROME_PATH':str(executable)}):
                with Browser() as browser:
                    profile=Path(browser.profile.name)
                    self.assertEqual(browser.call('Browser.getVersion')['product'],'isolated-pipe-test')
                    self.assertTrue(profile.is_dir())
                self.assertFalse(profile.exists())
                self.assertIsNotNone(browser.process.poll())


class TrackingMigrationTests(unittest.TestCase):
    def test_v5_upgrade_preserves_access_and_backs_up_once(self):
        import tempfile
        from pathlib import Path
        from store import Store
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            with store.connect() as con:
                con.execute("INSERT INTO settings VALUES('tracking-migration-marker','private-test-value')")
                con.execute('DROP TABLE tracking_checks')
                con.execute('DROP TABLE tracking_configs')
                con.execute('DELETE FROM migrations WHERE version=6')
            Store(directory)
            backups=list((Path(directory)/'backups').glob('*.sqlite3'))
            self.assertEqual(len(backups),1)
            with store.connect() as con:
                self.assertEqual(con.execute("SELECT value FROM settings WHERE key='tracking-migration-marker'").fetchone()[0],'private-test-value')
                self.assertTrue(con.execute('SELECT 1 FROM migrations WHERE version=6').fetchone())
            with sqlite3.connect(backups[0]) as con:
                self.assertFalse(con.execute('SELECT 1 FROM migrations WHERE version=6').fetchone())
            Store(directory)
            self.assertEqual(len(list((Path(directory)/'backups').glob('*.sqlite3'))),1)
