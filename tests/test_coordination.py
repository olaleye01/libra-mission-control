"""Ownership and team coordination acceptance tests through the owner API."""
import copy
import json
import uuid

from test_application import HttpFixture, report


class CoordinationTests(HttpFixture):
    def setUp(self):
        super().setUp()
        self.owner()

    def create(self, client=1, **changes):
        status, result, _ = self.call('POST','/api/shipments',{
            'command_id':uuid.uuid4().hex,'reason':'Owner coordination fixture','client_id':client,
            'changes':{'bl':uuid.uuid4().hex,'container_count':4,**changes}})
        self.assertEqual(status,200,result)
        return result['shipment']

    def save(self, job, endpoint, expected=200, **payload):
        body={'command_id':uuid.uuid4().hex,'revision':job['revision'],'reason':'Owner coordination update',**payload}
        status,result,_=self.call('POST',f"/api/shipments/{job['id']}/{endpoint}",body)
        self.assertEqual(status,expected,result)
        return result.get('shipment',result)

    def item(self, job, expected=200, item_id=None, **fields):
        return self.save(job,'coordination',expected,item_id=item_id,item={
            'title':'Manual compliance enquiry','next_action':'Check reported requirement','source':'Owner observation',**fields})

    def fetch(self, job):
        return self.call('GET',f"/api/shipments/{job['id']}")[1]['shipment']

    def test_delivery_location_create_update_clear_and_audit(self):
        job=self.create(delivery_location='Client warehouse, Example Road, Lagos')
        self.assertEqual(job['delivery_location'],'Client warehouse, Example Road, Lagos')
        self.assertEqual(job['state'],'Awaiting arrival')
        self.assertEqual(job['pending_count'],4)
        self.assertEqual(job['movements'],[])
        job=self.save(job,'update',changes={'delivery_location':'Revised warehouse, Example Estate'})
        history=self.fetch(job)['history'][-1]['detail']
        self.assertEqual(history['before']['delivery_location'],'Client warehouse, Example Road, Lagos')
        self.assertEqual(history['after']['delivery_location'],'Revised warehouse, Example Estate')
        self.assertEqual(self.call('GET','/api/shipments?search=Revised%20warehouse')[1]['total'],1)
        self.assertEqual(self.fetch(job)['operation']['delivery_location'],'Revised warehouse, Example Estate')
        self.save(job,'update',400,changes={'delivery_location':'x'*501})
        self.save(job,'update',400,changes={'delivery_location':None})
        self.assertEqual(self.fetch(job)['delivery_location'],'Revised warehouse, Example Estate')
        job=self.save(job,'update',changes={'delivery_location':''})
        self.assertEqual(self.fetch(job)['delivery_location'],'')
        self.assertIsNone(job['dates']['warehouse'])

    def test_legacy_location_is_unknown_without_writing_or_changing_imports(self):
        batch=self.preview(report({22:'Source agent'}))[1]['batch']['id']
        self.call('POST','/api/imports/'+batch+'/apply',{'confirm_test_import':True})
        job=self.fetch(self.call('GET','/api/shipments')[1]['shipments'][0])
        source=copy.deepcopy(job['source_snapshot'])
        self.assertEqual(job['delivery_location'],'')
        job=self.save(job,'update',changes={'delivery_location':'Owner-supplied warehouse'})
        self.assertEqual(job['source_snapshot'],source)
        legacy=copy.deepcopy(job['operation']);legacy.pop('delivery_location')
        raw=json.dumps(legacy)
        with self.httpd.app.store.connect() as con:
            con.execute('UPDATE job_updates SET data=? WHERE shipment_id=?',(raw,job['id']))
        restored=self.fetch(job)
        self.assertEqual(restored['delivery_location'],'')
        self.assertEqual(restored['source_snapshot'],source)
        with self.httpd.app.store.connect() as con:
            self.assertEqual(con.execute('SELECT data FROM job_updates WHERE shipment_id=?',(job['id'],)).fetchone()[0],raw)
        from server import Application
        from shipments import all_records
        app=Application(self.httpd.app.store.directory,self.sources)
        self.assertEqual(all_records(app)[0]['delivery_location'],'')

    def test_handler_alias_is_field_agent_and_owner_coordinates_by_default(self):
        job=self.create(handler='Agent A',dates={'paar':'2024-06-01'})
        self.assertEqual(job['field_agent'],'Agent A')
        self.assertEqual(job['handler'],'Agent A')
        self.assertEqual(job['import_officer'],'Owner')
        draft=next(a for a in job['actions'] if a['key']=='draft_approval')
        self.assertEqual(draft['responsible'],'Owner')
        self.assertEqual(draft['team'],'import_officer')
        self.assertEqual(draft['reminder_recipient'],'Owner')
        job=self.save(job,'update',changes={'field_agent':'Agent B','import_officer':'Officer C'})
        self.assertEqual(job['handler'],'Agent B')
        self.assertEqual(job['field_agent'],'Agent B')
        self.assertEqual(next(a['responsible'] for a in job['actions'] if a['key']=='draft_approval'),'Officer C')
        self.save(job,'update',422,changes={'handler':'Different','field_agent':'Conflict'})
        job=self.save(job,'update',changes={'field_agent':''})
        self.assertEqual(self.fetch(job)['field_agent'],'')
        self.assertEqual(self.fetch(job)['handler'],'')

    def test_import_role_mapping_preserves_raw_snapshot_and_read_does_not_write(self):
        batch=self.preview(report({22:'Source field agent'}))[1]['batch']['id']
        self.call('POST','/api/imports/'+batch+'/apply',{'confirm_test_import':True})
        listing=self.call('GET','/api/shipments')[1]['shipments'][0]
        job=self.fetch(listing)
        self.assertEqual(job['field_agent'],'Source field agent')
        self.assertEqual(job['import_officer'],'Owner')
        self.assertEqual(job['source_snapshot']['handler'],'Source field agent')
        self.assertEqual(job['raw'][22],'Source field agent')
        with self.httpd.app.store.connect() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM job_updates').fetchone()[0],0)
        job=self.save(job,'update',changes={'field_agent':'Updated agent'})
        self.assertEqual(job['source_snapshot']['handler'],'Source field agent')
        self.assertEqual(job['raw'][22],'Source field agent')
        self.assertEqual(self.call('GET','/api/imports/'+batch)[1]['batch']['records'][0]['handler'],'Source field agent')

    def test_legacy_conflicting_roles_and_saved_assignments_are_not_silently_lost(self):
        job=self.create()
        legacy=copy.deepcopy(job['operation'])
        for key in ('ownership_version','import_officer','coordination'):
            legacy.pop(key,None)
        legacy['handler']='Earlier handler'
        legacy['field_agent']='Explicit agent'
        legacy['followups']={'draft_approval':{'status':'awaiting_response','at':1,'responsible':'Earlier assignee','blocker':'','next_action':'','source':'Old entry'}}
        legacy['dates']['paar']='2024-06-01'
        raw=json.dumps(legacy)
        with self.httpd.app.store.connect() as con:
            con.execute('UPDATE job_updates SET data=? WHERE shipment_id=?',(raw,job['id']))
        loaded=self.fetch(job)
        self.assertEqual(loaded['field_agent'],'Explicit agent')
        self.assertEqual(loaded['operation']['legacy_handler'],'Earlier handler')
        self.assertIn('ownership_review',{i['code'] for i in loaded['issues']})
        draft=next(a for a in loaded['actions'] if a['key']=='draft_approval')
        self.assertEqual(draft['responsible'],'Earlier assignee')
        self.assertEqual(draft['team'],'unassigned')
        self.assertTrue(draft['assignment_review'])
        with self.httpd.app.store.connect() as con:
            self.assertEqual(con.execute('SELECT data FROM job_updates WHERE shipment_id=?',(job['id'],)).fetchone()[0],raw)
        corrected=self.save(loaded,'update',changes={'field_agent':'Confirmed agent'})
        self.assertNotIn('ownership_review',{i['code'] for i in corrected['issues']})
        self.assertEqual(self.fetch(corrected)['history'][-1]['detail']['before']['legacy_handler'],'Earlier handler')

    def test_assignment_and_reminder_recipient_are_independent(self):
        job=self.create(field_agent='Agent A',dates={'paar':'2024-06-01'})
        job=self.save(job,'followups',key='draft_approval',team='field_agent',status='awaiting_response',source='Owner request')
        draft=next(a for a in job['actions'] if a['key']=='draft_approval')
        self.assertEqual(draft['responsible'],'Agent A')
        self.assertEqual(draft['reminder_recipient'],'Owner')
        self.assertIn('awaiting_response',draft['queues'])
        self.assertNotIn('my_next',draft['queues'])
        self.assertIsNone(job['dates']['draft_received'])
        job=self.save(job,'followups',key='draft_approval',team='accounts',status='in_progress',responsible='Account staff',source='Owner assigned review')
        self.assertEqual(next(a['responsible'] for a in job['actions'] if a['key']=='draft_approval'),'Account staff')
        job=self.save(job,'followups',key='draft_approval',team='regulatory',status='open')
        self.assertEqual(next(a['responsible'] for a in job['actions'] if a['key']=='draft_approval'),'Unassigned')
        self.assertEqual(self.call('GET','/api/actions?team=regulatory')[1]['actions'][0]['reminder_recipient'],'Owner')
        job=self.save(job,'update',changes={'dates':{'assessment':'2024-06-02'},'sgd':'C-42'})
        self.assertNotIn('draft_approval',{a['key'] for a in job['actions']})
        self.assertIn('draft_approval',job['operation']['followups'])

    def test_regulatory_items_are_manual_and_do_not_create_authority_requirements(self):
        job=self.create()
        self.assertEqual(job['operation']['coordination'],{})
        self.assertFalse(any(a['team']=='regulatory' for a in job['actions']))
        job=self.item(job,team='regulatory',category='regulatory',authority='Owner-specified authority',blocker='Clarification pending',status='awaiting_response')
        item=next(iter(job['operation']['coordination'].values()))
        self.assertEqual(item['blocks_step'],'')
        action=next(a for a in job['actions'] if a['kind']=='coordination')
        self.assertEqual(action['authority'],'Owner-specified authority')
        self.assertEqual(action['team'],'regulatory')
        self.assertEqual(action['responsible'],'Unassigned')
        self.assertEqual(job['dates']['tdo'],None)
        self.assertEqual(job['dates']['customs_release'],None)
        self.assertEqual(job['closure_missing'],self.create(client=2)['closure_missing'])

    def test_resolve_reopen_audit_and_filters(self):
        job=self.item(self.create(),team='regulatory',category='regulatory',status='awaiting_response',authority='Manual authority')
        identifier=next(iter(job['operation']['coordination']))
        self.item(job,422,item_id=identifier,status='resolved')
        job=self.item(job,item_id=identifier,status='resolved',resolution_note='Owner checked response',resolution_date='2024-06-10')
        self.assertFalse(self.call('GET','/api/actions?team=regulatory')[1]['actions'])
        resolved=self.call('GET','/api/actions?team=regulatory&status=resolved')[1]['actions']
        self.assertEqual(len(resolved),1)
        self.assertEqual(resolved[0]['resolution_note'],'Owner checked response')
        self.assertEqual(self.call('GET','/api/actions')[1]['team_counts']['regulatory'],0)
        job=self.item(job,item_id=identifier,status='in_progress',next_action='Follow up a newly reported concern')
        self.assertEqual(job['operation']['coordination'][identifier]['resolution_date'],'2024-06-10')
        history=self.fetch(job)['history'][-1]['detail']
        self.assertEqual(history['before']['coordination'][identifier]['status'],'resolved')
        self.assertEqual(history['after']['coordination'][identifier]['status'],'in_progress')
        self.assertEqual(history['reason'],'Owner coordination update')

    def test_queues_and_team_filters_are_client_scoped(self):
        job=self.create(client=1,dates={'paar':'2024-06-01'})
        job=self.item(job,team='accounts',category='delivery',status='awaiting_response',blocker='Awaiting owner confirmation')
        other=self.item(self.create(client=2),team='regulatory',category='regulatory')
        result=self.call('GET','/api/actions?client_id=1')[1]
        self.assertEqual(result['queue_counts']['my_next'],1)
        self.assertEqual(result['queue_counts']['awaiting_response'],1)
        self.assertEqual(result['queue_counts']['clearing_blockers'],1)
        self.assertEqual(result['queue_counts']['delivery'],1)
        self.assertEqual(result['team_counts']['regulatory'],0)
        filtered=self.call('GET','/api/actions?client_id=1&team=accounts&queue=delivery')[1]
        self.assertEqual(len(filtered['actions']),1)
        self.assertEqual(filtered['actions'][0]['shipment_id'],job['id'])
        self.assertEqual(self.call('GET','/api/actions?client_id=2&team=accounts')[1]['actions'],[])
        self.assertEqual(self.call('GET','/api/actions?queue=made_up')[0],400)
        self.assertEqual(self.call('GET','/api/actions?status=made_up')[0],400)
        self.assertEqual(self.call('GET','/api/actions?team=made_up')[0],400)
        overview=self.call('GET','/api/overview?client_id=1')[1]
        self.assertEqual(overview['queue_counts'],result['queue_counts'])

    def test_only_explicit_holds_block_the_named_step_and_resolution_releases_it(self):
        job=self.create(dates={'do':'2024-06-01','tdo':'2024-06-02','customs_release':'2024-06-03'},
                        release_coverage={'do':4,'tdo':4,'customs_release':4})
        job=self.item(job,team='regulatory',blocks_step='gate_out')
        identifier=next(iter(job['operation']['coordination']))
        self.save(job,'movements',422,kind='gate_out',quantity=1,date='2024-06-04')
        # This is an observed exception, not an automated regulatory release.
        job=self.save(job,'movements',kind='gate_out',quantity=1,date='2024-06-04',exception_reason='Owner reports a physical movement despite the open issue')
        self.assertEqual(job['operation']['coordination'][identifier]['status'],'open')
        self.assertIn('manual_hold',{i['code'] for i in job['issues']})
        job=self.item(job,item_id=identifier,status='resolved',resolution_note='Owner confirms issue resolved',resolution_date='2024-06-05')
        job=self.save(job,'movements',kind='gate_out',quantity=1,date='2024-06-06')
        self.assertEqual(job['gate_out_count'],2)
        self.assertNotIn('manual_hold',{i['code'] for i in job['issues']})

    def test_completion_holds_and_tdo_holds_need_explicit_resolution(self):
        job=self.create(dates={'do':'2024-06-01','tdo':'2024-06-02','customs_release':'2024-06-03',
                              'ecd':'2024-06-06','client_invoiced':'2024-06-06'},
                        release_coverage={'do':4,'tdo':4,'customs_release':4},
                        closure={'empty_returns':{'applicability':'not_applicable','reason':'Owner confirmed'},
                                 'shipping_final':{'applicability':'not_applicable','reason':'Owner confirmed'}})
        job=self.save(job,'movements',kind='gate_out',quantity=4,date='2024-06-04')
        job=self.save(job,'movements',kind='warehouse',quantity=4,date='2024-06-05')
        job=self.item(job,blocks_step='completion',category='closure',team='qac')
        identifier=next(iter(job['operation']['coordination']))
        self.save(job,'update',422,changes={'completed':True})
        job=self.item(job,item_id=identifier,status='resolved',resolution_note='Owner checked closure evidence',resolution_date='2024-06-07')
        job=self.save(job,'update',changes={'completed':True})
        self.assertEqual(job['state'],'Completed')
        self.item(job,422,blocks_step='completion')
        second=self.create(client=2,dates={'do':'2024-06-01'})
        second=self.item(second,blocks_step='tdo')
        self.save(second,'update',422,changes={'dates':{'tdo':'2024-06-02'}})
        second=self.save(second,'update',changes={'dates':{'customs_release':'2024-06-03'}})
        self.assertEqual(second['dates']['customs_release'],'2024-06-03')
        from server import Application
        from shipments import all_records
        restored=Application(self.httpd.app.store.directory,self.sources)
        saved=next(r for r in all_records(restored) if r['id']==job['id'])
        self.assertEqual(saved['operation']['coordination'][identifier]['status'],'resolved')
        self.assertEqual(saved['state'],'Completed')

    def test_manual_tasks_do_not_require_repairs_to_unrelated_historical_release_gaps(self):
        batch=self.preview(report({18:'10-Jun-24'}))[1]['batch']['id']
        self.call('POST','/api/imports/'+batch+'/apply',{'confirm_test_import':True})
        job=self.fetch(self.call('GET','/api/shipments')[1]['shipments'][0])
        job=self.item(job,team='qac',next_action='Review source release gap')
        self.assertEqual(len(job['operation']['coordination']),1)
        self.assertIsNone(job['dates']['do'])

    def test_coordination_validation_revision_idempotency_and_auth(self):
        job=self.create()
        self.item(job,400,team='invented_team')
        self.item(job,400,next_action='')
        self.item(job,400,source='')
        self.item(job,400,blocks_step='invented_step')
        self.item(job,400,resolution_date='2024-02-30')
        job=self.item(job)
        identifier=next(iter(job['operation']['coordination']))
        other=self.create(client=2)
        self.item(other,404,item_id=identifier)
        body={'command_id':uuid.uuid4().hex,'revision':job['revision'],'reason':'One exact edit','item_id':identifier,
              'item':{'status':'awaiting_response'}}
        path=f"/api/shipments/{job['id']}/coordination"
        first=self.call('POST',path,body)
        self.assertEqual(first[0],200,first[1])
        self.assertEqual(self.call('POST',path,body)[1],first[1])
        body['command_id']=uuid.uuid4().hex
        self.assertEqual(self.call('POST',path,body)[0],409)
        self.assertEqual(self.call('POST',path,body,headers={'X-CSRF-Token':'bad'})[0],403)
        self.cookie=''
        self.assertEqual(self.call('GET','/api/actions')[0],401)
        self.assertEqual(self.call('POST',path,body)[0],401)
