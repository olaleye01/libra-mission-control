"""Slice 2 acceptance checks: actual HTTP mutations, revisions and rollback."""
import copy
import json
import sqlite3
import tempfile
import threading
import uuid
from pathlib import Path

from test_application import HttpFixture, report
import unittest
from server import Application
from store import Store


class OperationalTests(HttpFixture):
    def setUp(self):
        super().setUp()
        self.owner()

    def create(self, **changes):
        body = {'client_id': 2, 'command_id': uuid.uuid4().hex, 'reason': 'Owner test entry',
                'changes': {'bl': 'DEMO-ONLY', 'container_count': 4, **changes}}
        status, result, _ = self.call('POST', '/api/shipments', body)
        self.assertEqual(status, 200, result)
        return result['shipment']

    def update(self, job, changes, expected=200, **extra):
        status, result, _ = self.call('POST', f"/api/shipments/{job['id']}/update", {
            'command_id': uuid.uuid4().hex, 'revision': job['revision'], 'reason': 'Owner correction',
            'changes': changes, **extra})
        self.assertEqual(status, expected, result)
        return result.get('shipment', result)

    def move(self, job, kind, quantity, date='2024-06-10', expected=200, **extra):
        status, result, _ = self.call('POST', f"/api/shipments/{job['id']}/movements", {
            'command_id': uuid.uuid4().hex, 'revision': job['revision'], 'reason': 'Owner observed movement',
            'kind': kind, 'quantity': quantity, 'date': date, **extra})
        self.assertEqual(status, expected, result)
        return result.get('shipment', result)

    def ready(self, job):
        return self.update(job, {'dates': {'do': '2024-06-08', 'tdo': '2024-06-09', 'customs_release': '2024-06-10'},
                                 'release_coverage': {'do': 4, 'tdo': 4, 'customs_release': 4}})

    def detail(self, job):
        return self.call('GET', '/api/shipments/'+str(job['id']))[1]['shipment']

    def test_manual_clients_and_duplicate_bl_are_separate_and_acknowledged(self):
        job = self.create()
        self.assertIsNone(job['batch_id'])
        self.assertEqual(job['state'], 'Awaiting arrival')
        self.assertEqual(job['pending_count'], 4)
        body = {'command_id': uuid.uuid4().hex, 'reason': 'Second distinct job', 'client_id': 2, 'changes': {'bl': 'demo-only'}}
        self.assertEqual(self.call('POST', '/api/shipments', body)[0], 409)
        body['duplicate_reason'] = 'Two distinct jobs, owner confirmed'
        status, result, _ = self.call('POST', '/api/shipments', body)
        self.assertEqual(status, 200, result)
        self.assertNotEqual(result['shipment']['id'], job['id'])
        body.update(command_id=uuid.uuid4().hex, client_id=3, duplicate_reason='')
        self.assertEqual(self.call('POST', '/api/shipments', body)[0], 200)
        self.assertEqual(self.call('GET','/api/shipments?client_id=2')[1]['total'], 2)

    def test_idempotency_stale_revisions_and_audit_before_after(self):
        job = self.create()
        body = {'command_id': uuid.uuid4().hex, 'revision': 1, 'reason': 'Correct handler', 'changes': {'handler': 'QA owner'}}
        path = f"/api/shipments/{job['id']}/update"
        first = self.call('POST', path, body)
        self.assertEqual(first[0], 200, first[1])
        self.assertEqual(self.call('POST', path, body)[1], first[1])
        body['changes']['handler'] = 'Changed payload'
        self.assertEqual(self.call('POST', path, body)[0], 409)
        body['command_id'] = uuid.uuid4().hex
        self.assertEqual(self.call('POST', path, body)[0], 409)
        detail = self.detail(job)
        events = [e for e in detail['history'] if e['action'] == 'shipment_update']
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['detail']['before']['handler'], '')
        self.assertEqual(events[0]['detail']['after']['handler'], 'QA owner')

    def test_final_assessment_pair_clears_requirements_without_fabricating_history(self):
        job = self.create(dates={'paar': '2024-06-01'})
        self.assertIn('draft', {a['key'] for a in job['actions']})
        job = self.update(job, {'dates': {'assessment': '2024-06-02'}})
        self.assertFalse(job['assessment']['draft_requirements_cleared'])
        job = self.update(job, {'sgd': 'C-REFERENCE/42'})
        self.assertTrue(job['assessment']['draft_requirements_cleared'])
        self.assertNotIn('draft', {a['key'] for a in job['actions']})
        self.assertIn('duty_receipt', {a['key'] for a in job['actions']})
        self.assertIsNone(job['dates']['draft_approved'])
        self.assertEqual(job['assessment']['approval_by'], '')
        only_c = self.create(bl='C-ONLY', sgd='C42', dates={'paar': '2024-06-01'})
        self.assertFalse(only_c['assessment']['draft_requirements_cleared'])

    def test_awaiting_duty_is_reported_fact_with_completeness_exception(self):
        job = self.create(awaiting_duty_receipt=True)
        self.assertTrue(job['assessment']['final_received_reported'])
        self.assertIsNone(job['dates']['assessment'])
        self.assertIn('assessment_completeness', {i['code'] for i in job['issues']})
        self.assertIn('duty_receipt', {a['key'] for a in job['actions']})

    def test_nil_blank_unpaid_combined_and_rating_are_distinct(self):
        job = self.create(dates={'duty_receipt': '2024-06-01', 'eta': '2024-06-12'})
        self.assertEqual(job['operation']['invoices']['terminal']['request'], 'unknown')
        job = self.update(job, {'invoices': {'terminal': {'request': 'not_requested'}}})
        self.assertIsNone(job['operation']['invoices']['terminal']['received'])
        self.assertEqual(job['operation']['invoices']['terminal']['payment'], 'unknown')
        job = self.update(job, {'invoices': {'shipping': {'request': 'requested', 'received': '2024-06-01', 'coverage': 'combined',
                                 'payment': 'paid', 'payment_date': '2024-06-02', 'rated_through': '2024-06-12'}}})
        item = job['operation']['invoices']['shipping']
        self.assertNotEqual(item['payment_date'], item['rated_through'])
        self.assertNotIn('terminal_invoice', {a['key'] for a in job['actions']})
        self.assertFalse(any('expiry' in a['key'] for a in job['actions']))
        self.update(job, {'invoices': {'terminal': {'payment': 'not_paid', 'payment_date': '2024-06-02'}}}, 422)

    def test_tdo_requires_do_but_customs_can_follow_tdo(self):
        job = self.create()
        self.update(job, {'dates': {'tdo': '2024-06-09'}}, 422)
        job = self.update(job, {'dates': {'do': '2024-06-08', 'tdo': '2024-06-09'}})
        self.assertIsNone(job['dates']['customs_release'])
        self.move(job, 'gate_out', 1, expected=422)
        job = self.update(job, {'dates': {'customs_release': '2024-06-10'}})
        self.move(job, 'gate_out', 1, expected=422)  # Dates alone do not establish count coverage.
        job = self.ready(job)
        job = self.move(job, 'gate_out', 2)
        self.assertEqual(job['state'], 'In delivery')
        self.assertEqual(job['pending_count'], 4)
        job = self.move(job, 'warehouse', 1)
        self.assertEqual(job['pending_count'], 3)

    def test_counts_release_coverage_and_dates_gate_each_movement(self):
        job = self.ready(self.create())
        self.move(job, 'warehouse', 1, expected=422)
        self.move(job, 'gate_out', 1, date='2024-06-09', expected=422)
        job = self.update(job, {'release_coverage': {'customs_release': 2}})
        self.move(job, 'gate_out', 3, expected=422)
        job = self.move(job, 'gate_out', 2)
        self.move(job, 'warehouse', 3, expected=422)
        self.move(job, 'gate_out', 3, expected=422)
        job = self.move(job, 'warehouse', 2)
        self.update(job, {'container_count': 1}, 422)
        self.assertEqual(self.detail(job)['delivered_count'], 2)

    def test_duplicate_loads_require_confirmation_and_corrections_append(self):
        job = self.ready(self.create())
        job = self.move(job, 'gate_out', 2)
        first = job['movements'][0]['id']
        self.move(job, 'gate_out', 2, expected=409)
        job = self.move(job, 'gate_out', 2, confirm_duplicate=True)
        job = self.move(job, 'warehouse', 4)
        self.assertEqual(job['state'], 'Delivered')
        self.move(job, 'gate_out', 0, supersedes=first, expected=422)
        job = self.move(job, 'gate_out', 0, supersedes=first, exception_reason='Reported gate-out omitted; checking records')
        self.assertEqual(len(job['movements']), 4)
        self.assertEqual(job['gate_out_count'], 2)
        self.assertEqual(job['delivered_count'], 4)
        self.assertIn('operational_release_review', {i['code'] for i in job['issues']})
        self.update(job, {'completed': True}, 422)
        self.move(job, 'gate_out', 2, supersedes=first, expected=409)
        cancelled = job['movements'][-1]['id']
        job = self.move(job, 'gate_out', 2, supersedes=cancelled, confirm_duplicate=True)
        self.assertFalse(any(i['code']=='operational_release_review' for i in job['issues']))

    def test_completion_requires_reconciliation_ecd_and_applicability(self):
        job = self.ready(self.create())
        job = self.move(job, 'gate_out', 4)
        job = self.move(job, 'warehouse', 4)
        self.update(job, {'completed': True}, 422)
        job = self.update(job, {'dates': {'ecd': '2024-06-12', 'client_invoiced': '2024-06-12'}})
        self.update(job, {'completed': True}, 422)
        self.update(job, {'closure': {'shipping_final': {'applicability': 'not_applicable'}}}, 400)
        job = self.update(job, {'closure': {'shipping_final': {'applicability': 'not_applicable', 'reason': 'This shipping line does not require it'},
                                            'empty_returns': {'applicability': 'required', 'date': '2024-06-12'}}, 'completed': True})
        self.assertEqual(job['state'], 'Completed')
        self.update(job, {'dates': {'ecd': None}}, 422)
        self.assertEqual(self.detail(job)['state'], 'Completed')
        job = self.update(job, {'completed': False, 'dates': {'ecd': None}})
        self.assertEqual(job['state'], 'Delivered')

    def test_import_overlay_keeps_source_and_requires_movement_reconciliation(self):
        batch = self.preview(report({12:'10-Jun-24', 13:'C-RAW', 21:'Awaiting draft assessment',26:'15-Jun-24'}))[1]['batch']['id']
        self.call('POST', '/api/imports/'+batch+'/apply', {'confirm_test_import': True})
        job = self.call('GET','/api/shipments')[1]['shipments'][0]
        job = self.detail(job)
        self.assertEqual(job['review_status'], 'Historical proposal')
        self.assertTrue(job['assessment']['draft_requirements_cleared'])
        self.assertIn('draft_comment_conflict', {i['code'] for i in job['issues']})
        self.move(job,'gate_out',1, expected=422)
        original = copy.deepcopy(job['source_snapshot'])
        job = self.update(job, {'handler': 'Owner updated handler'})
        self.assertEqual(job['state'], 'Delivered')
        self.assertIsNone(job['pending_count'])
        self.assertEqual(job['source_snapshot'], original)
        preview = self.call('GET','/api/imports/'+batch)[1]['batch']
        self.assertEqual(preview['records'][0], original)
        job = self.update(job, {'reconciled': True})
        self.assertEqual(job['pending_count'], 4)
        self.assertNotEqual(job['state'],'Delivered')

    def test_calendar_boundaries_awaiting_response_and_resolution(self):
        job = self.create(dates={'eta': '2024-06-12'})
        self.assertFalse(self.call('GET','/api/actions?as_of=2024-06-06')[1]['actions'])
        actions = self.call('GET','/api/actions?as_of=2024-06-07')[1]['actions']
        self.assertEqual({a['key'] for a in actions}, {'shipping_invoice','rotation','paar','obl'})
        status, result, _ = self.call('POST', f"/api/shipments/{job['id']}/followups", {'command_id': uuid.uuid4().hex,
            'revision': job['revision'], 'reason': 'Owner requested document', 'key': 'paar', 'status': 'awaiting_response',
            'responsible':'Owner', 'source':'Owner phone call', 'blocker':'Client response pending'})
        self.assertEqual(status,200,result)
        job = result['shipment']
        self.assertEqual(next(a for a in job['actions'] if a['key']=='paar')['status'],'awaiting_response')
        job = self.update(job, {'dates': {'paar':'2024-06-08','berth':'2024-06-10'}})
        self.assertNotIn('paar',{a['key'] for a in job['actions']})
        self.assertNotIn('tdo_age',{a['key'] for a in self.call('GET','/api/actions?as_of=2024-06-15')[1]['actions']})
        actions = self.call('GET','/api/actions?as_of=2024-06-16')[1]['actions']
        self.assertIn('tdo_age',{a['key'] for a in actions})
        self.assertIn('confirm TDO',next(a['next_action'] for a in actions if a['key']=='tdo_age'))
        self.assertEqual(self.call('GET','/api/actions?as_of=2024-02-30')[0],400)

    def test_ecd_day_seven_and_split_anchor_are_explicit(self):
        job = self.ready(self.create())
        job = self.move(job,'gate_out',4)
        job = self.move(job,'warehouse',4)
        for as_of, due in [('2024-06-16',False),('2024-06-17',True)]:
            keys={a['key'] for a in self.call('GET','/api/actions?as_of='+as_of)[1]['actions']}
            self.assertEqual('ecd' in keys,due)
        warehouse = next(e for e in job['movements'] if e['kind']=='warehouse')
        job=self.move(job,'warehouse',2,supersedes=warehouse['id'])
        job=self.move(job,'warehouse',2,date='2024-06-11')
        self.assertIn('split delivery',next(a['next_action'] for a in job['actions'] if a['key']=='ecd'))

    def test_bad_payload_auth_and_atomic_rollback(self):
        job = self.create()
        self.update(job, {'container_count':True},400)
        self.update(job, {'dates':{'gate_out':'2024-06-10'}},400)
        self.update(job, {'dates':{'paar':'2024-02-30'}},400)
        self.update(job, {'dates':{'draft_approved':'2024-06-10'}},422)
        self.update(job, {'invoices':{'unknown':{}}},400)
        self.update(job, {'completed':'yes'},400)
        self.assertEqual(self.detail(job)['revision'],1)
        self.assertEqual(len(self.detail(job)['history']),1)
        self.assertEqual(self.call('POST','/api/shipments',{'changes':{'bl':'X'}})[0],400)
        self.assertEqual(self.call('POST',f"/api/shipments/{job['id']}/update",{},headers={'X-CSRF-Token':'bad'})[0],403)
        self.cookie=''
        self.assertEqual(self.call('POST','/api/shipments',{})[0],401)

    def test_concurrent_edits_accept_only_one_revision(self):
        job = self.create()
        from operations import execute
        from core import ApiError
        results = []
        barrier = threading.Barrier(2)
        def save(handler):
            barrier.wait()
            try:
                execute(self.httpd.app, 'update', {'command_id':uuid.uuid4().hex, 'revision':job['revision'],
                        'reason':'Concurrent owner save', 'changes':{'handler':handler}}, job['id'])
                results.append(200)
            except ApiError as exc:
                results.append(exc.status)
        threads = [threading.Thread(target=save,args=(name,)) for name in ('First','Second')]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(results),[200,409])
        self.assertEqual(self.detail(job)['revision'],2)

    def test_unknown_total_does_not_hide_known_berthing(self):
        job=self.create(container_count=None,dates={'berth':'2024-06-01'})
        self.assertEqual(job['state'],'In clearing')
        self.assertIsNone(job['pending_count'])
        self.move(job,'gate_out',1,expected=422)

    def test_reopen_persists_manual_job_movements_and_revisions(self):
        job = self.move(self.ready(self.create()),'gate_out',2)
        replacement = Application(self.httpd.app.store.directory,self.sources)
        from shipments import all_records
        restored = all_records(replacement)[0]
        self.assertEqual(restored['revision'],job['revision'])
        self.assertEqual(restored['gate_out_count'],2)


class MigrationTests(unittest.TestCase):
    def test_v1_import_rows_survive_nullable_source_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'libra-test.sqlite3'
            with sqlite3.connect(path) as con:
                con.executescript('''CREATE TABLE migrations(version INTEGER PRIMARY KEY);
                    INSERT INTO migrations VALUES(1);
                    CREATE TABLE shipments(id INTEGER PRIMARY KEY,client_id INTEGER NOT NULL,batch_id TEXT NOT NULL,source_row INTEGER NOT NULL,created_at REAL NOT NULL,UNIQUE(batch_id,source_row));
                    INSERT INTO shipments VALUES(7,1,'old-batch',42,1);''')
            # A valid v1 shipment references a real client and import batch.
            # Bootstrap the other v1 tables, then insert the source before migration.
            with sqlite3.connect(path) as con:
                con.executescript("""CREATE TABLE clients(id INTEGER PRIMARY KEY,name TEXT NOT NULL COLLATE NOCASE UNIQUE,created_at REAL NOT NULL);
                    INSERT INTO clients VALUES(1,'GZI',1);
                    CREATE TABLE batches(id TEXT PRIMARY KEY, client_id INTEGER NOT NULL,filename TEXT NOT NULL,sha256 TEXT NOT NULL,report_date TEXT,created_at REAL NOT NULL,status TEXT NOT NULL DEFAULT 'preview',summary TEXT NOT NULL,mapping TEXT NOT NULL,UNIQUE(client_id,sha256));
                    INSERT INTO batches VALUES('old-batch',1,'test.csv','fake-test-hash',NULL,1,'applied','{}','gzi-v1');""")
            store=Store(directory)
            with store.connect() as con:
                self.assertEqual(tuple(con.execute('SELECT * FROM shipments').fetchone()),(7,1,'old-batch',42,1))
                self.assertEqual(con.execute('SELECT COUNT(*) FROM migrations').fetchone()[0],3)
            self.assertEqual(len(list((Path(directory)/'backups').glob('*.sqlite3'))),1)
            with sqlite3.connect(next((Path(directory)/'backups').glob('*.sqlite3'))) as backup:
                self.assertEqual(backup.execute('SELECT id FROM shipments').fetchone()[0],7)
            Store(directory)  # Reopening migration is idempotent.
            self.assertEqual(len(list((Path(directory)/'backups').glob('*.sqlite3'))),1)
