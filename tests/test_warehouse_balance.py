"""Remaining-count entry must reconcile actual movements, not create a second balance."""
import uuid
from test_application import HttpFixture, report


class WarehouseBalanceTests(HttpFixture):
    def setUp(self):
        super().setUp()
        self.owner()

    def create(self, total=4):
        status,result,_=self.call('POST','/api/shipments',{'command_id':uuid.uuid4().hex,'reason':'QA job',
            'client_id':1,'changes':{'bl':'BALANCE-'+uuid.uuid4().hex,'container_count':total}})
        self.assertEqual(status,200,result)
        return result['shipment']

    def update(self, job, changes=None, balance=None, expected=200, **extra):
        body={'command_id':uuid.uuid4().hex,'revision':job['revision'],'reason':'Owner delivery update','changes':changes or {},**extra}
        if balance is not None:
            body['warehouse_balance']=balance
        status,result,_=self.call('POST',f"/api/shipments/{job['id']}/update",body)
        self.assertEqual(status,expected,result)
        return result.get('shipment',result)

    def gated(self, job):
        job=self.update(job,{'dates':{'do':'2024-06-01','tdo':'2024-06-02','customs_release':'2024-06-03'},
                             'release_coverage':{'do':4,'tdo':4,'customs_release':4}})
        status,result,_=self.call('POST',f"/api/shipments/{job['id']}/movements",{'command_id':uuid.uuid4().hex,
            'revision':job['revision'],'reason':'Reported gate-out','kind':'gate_out','quantity':4,'date':'2024-06-04'})
        self.assertEqual(status,200,result)
        return result['shipment']

    def detail(self, job):
        return self.call('GET',f"/api/shipments/{job['id']}")[1]['shipment']

    def test_partial_and_zero_pending_append_real_arrivals(self):
        job=self.gated(self.create())
        job=self.update(job,balance={'pending_count':2,'date':'2024-06-05'})
        self.assertEqual(job['pending_count'],2)
        self.assertEqual(job['delivered_count'],2)
        self.assertEqual(job['gate_out_count'],4)
        self.assertEqual(job['state'],'In delivery')
        event=job['movements'][-1]
        self.assertEqual((event['kind'],event['quantity'],event['date']),('warehouse',2,'2024-06-05'))
        job=self.update(job,balance={'pending_count':0,'date':'2024-06-06'})
        self.assertEqual(job['pending_count'],0)
        self.assertEqual(job['delivered_count'],4)
        self.assertEqual(job['state'],'Delivered')
        self.assertEqual(job['dates']['warehouse'],'2024-06-06')
        self.assertNotIn('Completed',job['state'])
        audit=self.detail(job)['history'][-1]['detail']
        self.assertEqual(audit['warehouse_balance']['pending_count'],0)
        self.assertEqual(audit['event']['quantity'],2)
        self.assertEqual(len([e for e in job['movements'] if e['kind']=='gate_out']),1)

    def test_unknown_total_invalid_counts_and_unchanged_fields_rollback(self):
        unknown=self.create(None)
        self.update(unknown,balance={'pending_count':0,'date':'2024-06-05'},expected=422)
        job=self.create()
        for value in (True,-1,5,1.5,None,'2'):
            self.update(job,{'handler':'Must not save'},balance={'pending_count':value,'date':'2024-06-05'},expected=400)
        self.assertEqual(self.detail(job)['revision'],1)
        self.assertEqual(self.detail(job)['handler'],'')
        self.update(job,{'pending_count':2},expected=400)
        job=self.update(job,{'container_count':6})
        self.assertEqual(job['pending_count'],6)
        self.assertEqual(job['movements'],[])

    def test_dates_gate_out_and_explicit_hold_remain_enforced(self):
        job=self.create()
        self.update(job,balance={'pending_count':2,'date':'2024-06-05'},expected=422)
        job=self.gated(job)
        self.update(job,balance={'pending_count':2},expected=400)
        self.update(job,balance={'pending_count':2,'date':'2024-02-30'},expected=400)
        self.update(job,balance={'pending_count':2,'date':'2999-01-01'},expected=400)
        self.update(job,balance={'pending_count':2,'date':'2024-06-03'},expected=422)
        status,result,_=self.call('POST',f"/api/shipments/{job['id']}/coordination",{'command_id':uuid.uuid4().hex,
            'revision':job['revision'],'reason':'Owner hold','item':{'title':'Check delivery','next_action':'Confirm position','source':'Owner report','blocks_step':'warehouse'}})
        self.assertEqual(status,200,result)
        job=result['shipment']
        self.update(job,balance={'pending_count':2,'date':'2024-06-05'},expected=422)
        job=self.update(job,balance={'pending_count':2,'date':'2024-06-05'},exception_reason='Actual delivery reported despite unresolved hold')
        self.assertEqual(job['delivered_count'],2)
        self.assertEqual(next(iter(job['operation']['coordination'].values()))['status'],'open')

    def test_corrections_replace_only_selected_arrival_and_keep_history(self):
        job=self.update(self.gated(self.create()),balance={'pending_count':1,'date':'2024-06-05'})
        old=job['movements'][-1]
        self.update(job,balance={'pending_count':2,'date':'2024-06-05'},expected=422)
        gate=next(e for e in job['movements'] if e['kind']=='gate_out')
        self.update(job,balance={'pending_count':2,'date':'2024-06-05','supersedes':gate['id']},expected=409)
        job=self.update(job,balance={'pending_count':2,'date':'2024-06-05','supersedes':old['id']})
        self.assertEqual(job['pending_count'],2)
        self.assertEqual(job['movements'][-1]['quantity'],2)
        self.assertEqual(job['movements'][-1]['supersedes'],old['id'])
        self.assertEqual(old['quantity'],3)
        self.update(job,balance={'pending_count':3,'date':'2024-06-05','supersedes':old['id']},expected=409)
        replacement=job['movements'][-1]
        job=self.update(job,balance={'pending_count':4,'supersedes':replacement['id']})
        self.assertEqual(job['delivered_count'],0)
        self.assertIsNone(job['dates']['warehouse'])
        self.assertEqual(job['movements'][-1]['quantity'],0)
        self.assertEqual(len(job['movements']),4)

    def test_duplicate_loads_need_confirmation_and_retries_are_idempotent(self):
        job=self.update(self.gated(self.create()),balance={'pending_count':2,'date':'2024-06-05'})
        self.update(job,balance={'pending_count':0,'date':'2024-06-05'},expected=409)
        body={'command_id':uuid.uuid4().hex,'revision':job['revision'],'reason':'Separate arrival confirmed',
              'changes':{},'warehouse_balance':{'pending_count':0,'date':'2024-06-05','confirm_duplicate':True}}
        path=f"/api/shipments/{job['id']}/update"
        first=self.call('POST',path,body)
        self.assertEqual(first[0],200,first[1])
        self.assertEqual(self.call('POST',path,body)[1],first[1])
        body['command_id']=uuid.uuid4().hex
        self.assertEqual(self.call('POST',path,body)[0],409)
        current=self.detail(job)
        self.assertEqual(current['delivered_count'],4)
        self.assertEqual(len(current['movements']),3)

    def test_import_reconciliation_is_explicit_and_preserves_source(self):
        batch=self.preview(report({20:'5-Jun-24'}))[1]['batch']['id']
        self.call('POST','/api/imports/'+batch+'/apply',{'confirm_test_import':True})
        job=self.detail(self.call('GET','/api/shipments')[1]['shipments'][0])
        source=job['source_snapshot']
        self.assertIsNone(job['pending_count'])
        self.update(job,balance={'pending_count':2,'date':'2024-06-05'},expected=422)
        job=self.update(job,{'reconciled':True},balance={'pending_count':2,'date':'2024-06-05'},
                        exception_reason='Owner reports historical warehouse arrivals; gate-out evidence pending')
        self.assertEqual(job['pending_count'],2)
        self.assertEqual(job['gate_out_count'],0)
        self.assertEqual(job['source_snapshot'],source)
        self.assertIn('operational_release_review',{i['code'] for i in job['issues']})
        self.update(job,{'completed':True},expected=422,exception_reason='Evidence still pending')

    def test_unchanged_balance_does_not_invent_an_arrival_and_can_correct_date(self):
        job=self.create()
        job=self.update(job,balance={'pending_count':4})
        self.assertEqual(job['movements'],[])
        self.assertIsNone(job['dates']['warehouse'])
        self.update(job,balance={'pending_count':4,'date':'2024-06-05'},expected=422)
        job=self.update(self.gated(job),balance={'pending_count':2,'date':'2024-06-05'})
        event=job['movements'][-1]
        job=self.update(job,balance={'pending_count':2,'date':'2024-06-06','supersedes':event['id']})
        self.assertEqual(job['pending_count'],2)
        self.assertEqual(job['dates']['warehouse'],'2024-06-06')

    def test_completed_job_correction_requires_reopening(self):
        job=self.update(self.gated(self.create()),balance={'pending_count':0,'date':'2024-06-05'})
        job=self.update(job,{'dates':{'ecd':'2024-06-06','client_invoiced':'2024-06-06'},
                             'closure':{'empty_returns':{'applicability':'not_applicable','reason':'Owner confirms'},
                                        'shipping_final':{'applicability':'not_applicable','reason':'Owner confirms'}},'completed':True})
        event=job['movements'][-1]
        self.update(job,balance={'pending_count':1,'date':'2024-06-05','supersedes':event['id']},expected=422)
        self.assertEqual(self.detail(job)['state'],'Completed')
        job=self.update(job,{'completed':False},balance={'pending_count':1,'date':'2024-06-05','supersedes':event['id']})
        self.assertEqual(job['state'],'In delivery')
        self.assertEqual(job['pending_count'],1)

    def test_new_arrival_and_other_job_fields_save_atomically(self):
        job=self.gated(self.create())
        job=self.update(job,{'handler':'New field agent'},balance={'pending_count':3,'date':'2024-06-05'})
        self.assertEqual(job['field_agent'],'New field agent')
        self.assertEqual(job['pending_count'],3)
        self.update(job,{'handler':'Must rollback'},balance={'pending_count':2},expected=400)
        self.assertEqual(self.detail(job)['field_agent'],'New field agent')
        self.assertEqual(self.detail(job)['pending_count'],3)
