"""Overview highlights use existing workflow evidence and isolated application storage."""
import base64
import uuid

from test_application import HttpFixture, report


class OverviewTests(HttpFixture):
    def setUp(self):
        super().setUp()
        self.owner()

    def create(self, client=1, **changes):
        status, result, _ = self.call('POST', '/api/shipments', {
            'client_id': client, 'command_id': uuid.uuid4().hex, 'reason': 'Overview test job',
            'duplicate_reason': 'Separate test shipment with the same reported BL',
            'changes': {'bl': uuid.uuid4().hex, 'container_count': 4, **changes}})
        self.assertEqual(status, 200, result)
        return result['shipment']

    def save(self, job, endpoint, **payload):
        status, result, _ = self.call('POST', '/api/shipments/{}/{}'.format(job['id'], endpoint), {
            'revision': job['revision'], 'command_id': uuid.uuid4().hex, 'reason': 'Overview test update', **payload})
        self.assertEqual(status, 200, result)
        return result['shipment']

    def item(self, job, **item):
        return self.save(job, 'coordination', item={
            'title': 'Owner-recorded enquiry', 'next_action': 'Review owner evidence',
            'source': 'Synthetic owner report', **item})

    def overview(self, query=''):
        status, result, _ = self.call('GET', '/api/overview' + query)
        self.assertEqual(status, 200, result)
        return result

    def test_empty_workspace_keeps_zero_counts_and_empty_highlights(self):
        overview = self.overview()
        self.assertEqual(overview['total'], 0)
        self.assertEqual(overview['briefing'], {
            'action_count': 0, 'shipment_count': 0, 'undated_count': 0, 'items': []})
        self.assertEqual(overview['attention'], {
            'shipment_count': 0, 'review_count': 0, 'hold_count': 0, 'items': []})

    def test_briefing_counts_actions_but_caps_distinct_jobs_and_respects_assignments(self):
        jobs = [self.create(dates={'paar': '2024-06-01'}) for _ in range(4)]
        job = self.item(jobs[0])
        self.item(job)
        other_team = self.create(dates={'paar': '2024-06-01'})
        self.save(other_team, 'followups', key='draft_approval', team='accounts', status='open')
        awaiting = self.create(dates={'paar': '2024-06-01'})
        self.save(awaiting, 'followups', key='draft_approval', team='import_officer', status='awaiting_response')
        overview = self.overview()
        briefing = overview['briefing']
        self.assertEqual(briefing['action_count'], 6)
        self.assertEqual(briefing['action_count'], overview['queue_counts']['my_next'])
        self.assertEqual(briefing['shipment_count'], 4)
        self.assertEqual(len(briefing['items']), 3)
        identifiers = [item['shipment_id'] for item in briefing['items']]
        self.assertEqual(len(set(identifiers)), 3)
        self.assertNotIn(other_team['id'], identifiers)
        self.assertNotIn(awaiting['id'], identifiers)
        self.assertTrue(all(item['tab'] == 'followups' for item in briefing['items']))
        self.assertTrue(all(item['as_of'] and not item['historical'] for item in briefing['items']))
        self.assertEqual(self.overview()['briefing'], briefing)

    def test_attention_prioritises_explicit_holds_blockers_then_record_questions(self):
        hold = self.item(self.create(bl='REPEATED-BL'), blocks_step='gate_out', team='regulatory')
        self.item(hold, blocks_step='tdo', team='qac')
        blocker = self.item(self.create(bl='REPEATED-BL'), blocker='Waiting for an owner-specified response',
                            team='accounts', status='awaiting_response')
        reviews = [self.create(awaiting_duty_receipt=True) for _ in range(4)]
        resolved = self.item(self.create(), blocker='Earlier blocker', blocks_step='tdo', status='resolved',
                             resolution_note='Owner resolved the enquiry', resolution_date='2024-06-01')
        result = self.overview()['attention']
        self.assertEqual(result['shipment_count'], 6)
        self.assertEqual(result['hold_count'], 1)
        self.assertEqual(result['review_count'], 5)
        self.assertEqual(len(result['items']), 4)
        self.assertEqual([item['kind'] for item in result['items']], ['hold', 'blocker', 'review', 'review'])
        self.assertEqual([item['shipment_id'] for item in result['items'][:2]], [hold['id'], blocker['id']])
        self.assertEqual(result['items'][0]['tab'], 'coordination')
        self.assertEqual(result['items'][1]['detail'], 'Waiting for an owner-specified response')
        self.assertTrue(all(item['tab'] == 'milestones' for item in result['items'][2:]))
        self.assertNotIn(resolved['id'], [item['shipment_id'] for item in result['items']])
        self.assertTrue({item['shipment_id'] for item in result['items'][2:]} <= {job['id'] for job in reviews})

    def test_client_department_and_hidden_scopes_apply_to_every_highlight(self):
        first = self.item(self.create(client=1, dates={'paar': '2024-06-01'}), blocks_step='tdo')
        second = self.item(self.create(client=3, dates={'paar': '2024-06-01'}), blocks_step='gate_out')
        status, result, _ = self.call('POST', '/api/departments', {
            'name': 'Other test department', 'command_id': uuid.uuid4().hex, 'reason': 'Overview scope test'})
        self.assertEqual(status, 200, result)
        department = result['department']['id']
        client = next(item for item in self.call('GET', '/api/clients')[1]['clients'] if item['id'] == 3)
        status, result, _ = self.call('POST', '/api/clients/3/update', {
            'revision': client['revision'], 'command_id': uuid.uuid4().hex, 'reason': 'Move test client',
            'changes': {'department_id': department}})
        self.assertEqual(status, 200, result)
        scoped = self.overview('?department_id={}'.format(department))
        self.assertEqual(scoped['total'], 1)
        self.assertEqual(scoped['briefing']['shipment_count'], 1)
        self.assertEqual(scoped['attention']['items'][0]['shipment_id'], second['id'])
        self.assertEqual(self.overview('?client_id=1')['attention']['items'][0]['shipment_id'], first['id'])
        client = result['client']
        status, result, _ = self.call('POST', '/api/clients/3/update', {
            'revision': client['revision'], 'command_id': uuid.uuid4().hex, 'reason': 'Hide test client',
            'changes': {'hidden': True}})
        self.assertEqual(status, 200, result)
        hidden = self.overview('?department_id={}'.format(department))
        self.assertEqual(hidden['briefing']['items'], [])
        self.assertEqual(hidden['attention']['items'], [])
        self.assertEqual(self.overview('?department_id={}&include_hidden=1'.format(department))['attention']['shipment_count'], 1)

    def test_historical_cutoffs_stay_unknown_or_source_dated_without_today_age(self):
        content = report({3: 'UNKNOWN-CUTOFF', 6: '01-Jun-24', 10: '02-Jun-24', 7: '03-Jun-24'})
        batch = self.preview(content)[1]['batch']['id']
        self.assertEqual(self.call('POST', '/api/imports/' + batch + '/apply', {'confirm_test_import': True})[0], 200)
        historical = self.overview()['briefing']
        self.assertEqual(historical['action_count'], 1)
        self.assertEqual(historical['undated_count'], 1)
        self.assertEqual(historical['items'][0]['key'], 'draft_approval')
        self.assertIsNone(historical['items'][0]['as_of'])
        self.assertTrue(historical['items'][0]['historical'])
        content = report({3: 'DATED-CUTOFF', 6: '01-Jun-24', 7: '03-Jun-24', 10: '02-Jun-24'})
        status, result, _ = self.call('POST', '/api/imports/preview', {
            'client_id': 1, 'filename': 'historical-dated.csv', 'report_date': '2024-06-10',
            'content_base64': base64.b64encode(content).decode()})
        self.assertEqual(status, 200, result)
        batch = result['batch']['id']
        self.assertEqual(self.call('POST', '/api/imports/' + batch + '/apply', {'confirm_test_import': True})[0], 200)
        briefing = self.overview()['briefing']
        dated = next(item for item in briefing['items'] if item['bl'] == 'DATED-CUTOFF')
        self.assertEqual(dated['as_of'], '2024-06-10')
        self.assertEqual(dated['key'], 'tdo_age')
        self.assertIn('7 days since berthing', dated['next_action'])
        self.assertEqual(briefing['undated_count'], 1)

    def test_blank_source_cells_are_not_confirmed_missing_documents_and_reads_do_not_write(self):
        batch = self.preview(b'BL,PAAR,OBL,Container count,Container size,File Handler\nUNKNOWN-DOCUMENTS,,,4,20,Synthetic agent\n')[1]['batch']['id']
        self.assertEqual(self.call('POST', '/api/imports/' + batch + '/apply', {'confirm_test_import': True})[0], 200)
        with self.httpd.app.store.connect() as con:
            before = tuple(con.execute('SELECT COUNT(*) FROM ' + name).fetchone()[0]
                           for name in ('audit', 'job_updates', 'movements'))
        overview = self.overview()
        self.assertEqual(overview['briefing']['items'], [])
        self.assertEqual(overview['attention']['items'], [])
        with self.httpd.app.store.connect() as con:
            after = tuple(con.execute('SELECT COUNT(*) FROM ' + name).fetchone()[0]
                          for name in ('audit', 'job_updates', 'movements'))
        self.assertEqual(after, before)

    def test_unreconciled_manual_job_is_not_labelled_a_historical_report(self):
        job = self.create(container_count=None, reconciled=False, dates={'paar': '2024-06-01'}, awaiting_duty_receipt=True)
        result = self.overview()
        briefing = result['briefing']['items'][0]
        self.assertEqual(briefing['shipment_id'], job['id'])
        self.assertFalse(briefing['historical'])
        self.assertIsNone(briefing['as_of'])
        self.assertEqual(result['briefing']['undated_count'], result['briefing']['action_count'])
        attention = result['attention']['items'][0]
        self.assertFalse(attention['historical'])
        self.assertIsNone(attention['as_of'])
