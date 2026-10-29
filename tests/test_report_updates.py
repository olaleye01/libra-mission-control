"""Reviewed CSV revisions update identities without erasing evidence or owner work."""
import copy
import base64
import json
import time
import uuid

from test_application import HttpFixture, report


class ReportUpdateTests(HttpFixture):
    def setUp(self):
        super().setUp()
        self.owner()

    def stage(self, content, cutoff=None):
        status, result, _ = self.call('POST', '/api/imports/preview', {'client_id':1,'filename':'test.csv', 'content_base64':base64.b64encode(content).decode(),'report_date':cutoff})
        self.assertEqual(status, 200, result)
        return result['batch']['id']

    def first(self, content=None):
        batch = self.stage(content or report({2:'Original cargo', 6:'10-Jun-24', 10:'1-Jun-24'}))
        status, result, _ = self.call('POST', '/api/imports/'+batch+'/apply', {'confirm_test_import':True})
        self.assertEqual(status, 200, result)
        return self.jobs()[0]

    def jobs(self):
        return self.call('GET','/api/shipments')[1]['shipments']

    def detail(self, job):
        return self.call('GET','/api/shipments/'+str(job['id']))[1]['shipment']

    def review(self, batch):
        status, result, _ = self.call('GET','/api/imports/'+batch+'/review-updates')
        self.assertEqual(status, 200, result)
        return result['review']

    def sync(self, batch, expected=200, body=None):
        payload = body or {'confirm_test_import':True,'reason':'Reviewed updated test report',
                          'command_id':uuid.uuid4().hex,'plan_token':self.review(batch)['token']}
        status, result, _ = self.call('POST','/api/imports/'+batch+'/review-updates',payload)
        self.assertEqual(status, expected, result)
        return result

    def test_unique_matching_job_updates_in_place_and_keeps_both_sources(self):
        job = self.first()
        original = copy.deepcopy(self.detail(job)['source_snapshot'])
        batch = self.stage(report({2:'Updated cargo', 7:'10-Jun-24', 12:'11-Jun-24', 13:'C42'}))
        self.assertEqual(self.review(batch)['counts']['update'],1)
        self.assertEqual(self.call('POST','/api/imports/'+batch+'/apply',{'confirm_test_import':True})[0],409)
        self.sync(batch)
        self.assertEqual(len(self.jobs()),1)
        saved = self.detail(job)
        self.assertEqual(saved['id'],job['id'])
        self.assertEqual(saved['description'],'Updated cargo')
        self.assertEqual(saved['state'],'In clearing')
        self.assertEqual(saved['source_snapshot'],original)
        self.assertEqual(len(saved['report_history']),1)
        self.assertEqual(saved['report_history'][0]['record']['description'],'Updated cargo')
        self.assertEqual(saved['revision'],1)
        self.assertTrue(saved['assessment']['draft_requirements_cleared'])
        self.assertIsNone(saved['dates']['draft_approved'])
        self.assertEqual(self.review(batch)['counts']['unchanged'],1)
        self.sync(batch)
        self.assertEqual(len(self.detail(job)['report_history']),1)

    def test_blank_missing_and_uninterpretable_fields_do_not_erase_values(self):
        job = self.first()
        batch = self.stage(b'BL,ETA,DESCRIPTION\nBL1,uninterpretable,\n')
        self.sync(batch)
        saved = self.detail(job)
        self.assertEqual(saved['description'],'Original cargo')
        self.assertEqual(saved['dates']['eta'],'2024-06-10')
        self.assertEqual(saved['dates']['paar'],'2024-06-01')
        self.assertEqual(saved['container_count'],4)
        self.assertIsNone(saved['current_source_snapshot']['dates']['eta'])

    def test_owner_edits_assignments_and_followups_are_preserved(self):
        job = self.first()
        status, result, _ = self.call('POST',f"/api/shipments/{job['id']}/update",{
            'revision':0,'command_id':uuid.uuid4().hex,'reason':'Owner corrections',
            'changes':{'description':'Owner description','import_officer':'Officer X','delivery_location':'Owner warehouse'}})
        self.assertEqual(status,200,result)
        batch = self.stage(report({2:'Report description',7:'10-Jun-24'}))
        self.assertIn('description',self.review(batch)['rows'][0]['kept_fields'])
        self.sync(batch)
        saved = self.detail(job)
        self.assertEqual(saved['description'],'Owner description')
        self.assertEqual(saved['delivery_location'],'Owner warehouse')
        self.assertEqual(saved['import_officer'],'Officer X')
        self.assertEqual(saved['dates']['berth'],'2024-06-10')
        self.assertEqual(saved['revision'],2)

    def test_repeated_incoming_bls_and_ambiguous_existing_jobs_block_atomically(self):
        self.first()
        batch = self.stage(report({2:'New one'},{3:'BL1',2:'New two'}))
        self.assertEqual(self.review(batch)['counts']['review'],2)
        self.sync(batch,409)
        self.assertEqual(len(self.jobs()),1)
        self.assertEqual(self.jobs()[0]['description'],'Original cargo')
        self.assertEqual(self.call('POST','/api/imports/'+batch+'/apply',{'confirm_test_import':True})[0],409)

    def test_first_report_repeated_bls_stay_separate_and_later_matches_need_review(self):
        batch=self.stage(report({},{3:'BL1'}))
        self.sync(batch)
        self.assertEqual(len(self.jobs()),2)
        newer=self.stage(report({2:'Changed'}))
        self.assertEqual(self.review(newer)['counts']['review'],1)
        self.sync(newer,409)
        self.assertEqual(len(self.jobs()),2)

    def test_new_bls_create_once_and_other_clients_are_not_matched(self):
        self.first()
        status, result, _=self.call('POST','/api/shipments',{'client_id':2,'command_id':uuid.uuid4().hex,
            'reason':'Other client','changes':{'bl':'BL2'}})
        self.assertEqual(status,200,result)
        batch=self.stage(report({2:'Updated'},{3:'BL2',2:'New client-specific job'}))
        plan=self.review(batch)
        self.assertEqual((plan['counts']['create'],plan['counts']['update']),(1,1))
        self.sync(batch)
        self.assertEqual(len(self.jobs()),3)
        self.assertEqual(self.call('GET','/api/clients')[1]['clients'][0]['shipment_count'],2)

    def test_stale_plan_and_tampered_token_make_no_changes_and_retry_is_idempotent(self):
        job=self.first()
        batch=self.stage(report({2:'Updated'}))
        body={'confirm_test_import':True,'reason':'Reviewed report','command_id':uuid.uuid4().hex,
              'plan_token':self.review(batch)['token']}
        self.call('POST',f"/api/shipments/{job['id']}/update",{'revision':0,'command_id':uuid.uuid4().hex,
            'reason':'Concurrent update','changes':{'import_officer':'New officer'}})
        self.sync(batch,409,body)
        body['plan_token']=self.review(batch)['token']
        result=self.sync(batch,body=body)
        self.assertEqual(self.sync(batch,body=body),result)
        body['reason']='Different request'
        self.sync(batch,409,body)
        self.assertEqual(len(self.detail(job)['report_history']),1)

    def test_existing_duplicate_rows_can_be_archived_without_deleting_sources(self):
        job=self.first()
        original=self.detail(job)['source_snapshot']
        batch=self.stage(report({2:'Updated source'},{3:'BL2'}))
        # Reproduce the old importer: all rows were inserted, even matching BLs.
        with self.httpd.app.store.connect() as con:
            con.execute('INSERT INTO shipments(client_id,batch_id,source_row,created_at) SELECT 1,batch_id,source_row,? FROM import_rows WHERE batch_id=?',(time.time(),batch))
            con.execute("UPDATE batches SET status='applied' WHERE id=?",(batch,))
        self.assertEqual(len(self.jobs()),3)
        self.assertEqual(self.review(batch)['duplicates_to_archive'],1)
        self.sync(batch)
        self.assertEqual(len(self.jobs()),2)
        self.assertEqual(self.detail(job)['source_snapshot'],original)
        self.assertEqual(self.detail(job)['description'],'Updated source')
        with self.httpd.app.store.connect() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM shipments').fetchone()[0],3)
            self.assertEqual(con.execute('SELECT count(*) FROM import_rows').fetchone()[0],3)
            self.assertEqual(con.execute('SELECT count(*) FROM shipment_aliases').fetchone()[0],1)
        self.assertEqual(self.call('GET','/api/clients')[1]['clients'][0]['shipment_count'],2)
        self.assertEqual(self.review(batch)['counts']['unchanged'],2)

    def test_duplicate_with_independent_edits_is_not_archived(self):
        self.first()
        batch=self.stage(report({2:'Changed'}))
        with self.httpd.app.store.connect() as con:
            cursor=con.execute('INSERT INTO shipments(client_id,batch_id,source_row,created_at) SELECT 1,batch_id,source_row,? FROM import_rows WHERE batch_id=?',(time.time(),batch))
            duplicate=cursor.lastrowid
            con.execute("UPDATE batches SET status='applied' WHERE id=?",(batch,))
        self.call('POST',f'/api/shipments/{duplicate}/update',{'revision':0,'command_id':uuid.uuid4().hex,
            'reason':'Independent edits','changes':{'delivery_location':'Separate job destination'}})
        self.assertEqual(self.review(batch)['counts']['review'],1)
        self.sync(batch,409)
        self.assertEqual(len(self.jobs()),2)

    def test_older_cutoff_does_not_replace_a_newer_report(self):
        batch=self.stage(report({2:'Newer'}),'2024-06-20')
        self.sync(batch)
        older=self.stage(report({2:'Older'}),'2024-06-10')
        self.assertEqual(self.review(older)['counts']['review'],1)
        self.sync(older,409)
        self.assertEqual(self.jobs()[0]['description'],'Newer')

    def test_operational_count_conflict_is_reviewed_without_changing_movements(self):
        job=self.first(report({8:'4',16:'3-Jun-24',17:'1-Jun-24',18:'2-Jun-24'}))
        status,result,_=self.call('POST',f"/api/shipments/{job['id']}/update",{
            'revision':0,'command_id':uuid.uuid4().hex,'reason':'Reconcile known releases',
            'changes':{'reconciled':True,'release_coverage':{'do':4,'tdo':4,'customs_release':4}}})
        self.assertEqual(status,200,result)
        self.call('POST',f"/api/shipments/{job['id']}/movements",{'revision':1,'command_id':uuid.uuid4().hex,
            'reason':'Actual gate-out','kind':'gate_out','quantity':4,'date':'2024-06-04'})
        batch=self.stage(report({8:'2',16:'3-Jun-24',17:'1-Jun-24',18:'2-Jun-24'}))
        self.assertEqual(self.review(batch)['counts']['review'],1)
        self.sync(batch,409)
        self.assertEqual(self.detail(job)['gate_out_count'],4)
        self.assertEqual(self.detail(job)['container_count'],4)

    def test_bl_matching_ignores_case_but_preserves_punctuation(self):
        job=self.first(report({3:'Bl-001'}))
        batch=self.stage(report({3:' bl-001 ',2:'Case matched'},{3:'BL001',2:'Distinct punctuation'}))
        self.assertEqual(self.review(batch)['counts']['update'],1)
        self.assertEqual(self.review(batch)['counts']['create'],1)
        self.sync(batch)
        self.assertEqual(len(self.jobs()),2)
        self.assertEqual(self.detail(job)['description'],'Case matched')
