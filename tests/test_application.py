"""Business and access checks. All writes use isolated temporary directories."""

import base64
import csv
import hashlib
import http.client
import io
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
from server import Application, make_server
from core import ApiError
from imports import batch_data, parse_date, preview_csv, stage

SOURCE = ROOT / "imports/sources/GZI-report-26-10-26.csv"
HEADERS = ['S/N', 'PRE-ALERT DATE', 'ITEM DESCRIPTION', 'BOL NO', 'TERMINAL', 'LINER', 'ETA', 'ATD',
           'CONT COUNT', 'CONT Size', 'PAAR DATE', 'OBL RECEIVED DATE', 'ASSESS. DATE', 'SGD NO',
           'DUTY RECEIVED DATE', 'CUSTOMS EXAM DATE', 'CUSTOMS RELEASE DATE', 'SHIPPING RELEASE DATE',
           'TDO DATE', 'GATE OUT DATE', 'ARRIVAL AT FACTORY', 'COMMENTS', 'File Handler', 'Remark',
           'Terminal Validty', 'PCA Final Closure', 'ECD', 'CLEARING Income', 'HAULAGE Income',
           'TOTAL PROJECTED INCOME', 'CLEARING Cost', 'HAULAGE Cost', 'TOTAL PROJECTED EXPENSES', '']


def report(*updates):
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(['LOADING/DELIVERY'] + [''] * 33)
    writer.writerow(HEADERS)
    for idx, fields in enumerate(updates, 1):
        row = [''] * 34
        row[0], row[3], row[4], row[5], row[8], row[9] = str(idx), f'BL{idx}', 'ONNE', 'MSC', '4', '20'
        for col, value in fields.items():
            row[col] = value
        writer.writerow(row)
    return stream.getvalue().encode()


class MappingTests(unittest.TestCase):
    def test_known_source_reconciles_and_retains_duplicate(self):
        if not SOURCE.exists():
            self.skipTest('Private GZI source not supplied')
        data = SOURCE.read_bytes()
        records, summary = preview_csv(data)
        self.assertEqual(hashlib.sha256(data).hexdigest(), 'ffc6339acf26316dbc97653686c615e9a3862555cea63bb7b9bc6ffefcafb2d5')
        self.assertEqual(summary['shipments'], 220)
        self.assertEqual(summary['unique_bls'], 219)
        self.assertEqual(summary['physical_rows'], 661)
        self.assertEqual(sum(summary['excluded'].values()) + len(records), 661)
        repeated = [r for r in records if any(i['code'] == 'duplicate_bl' for i in r['issues'])]
        self.assertEqual(len(repeated), 2)
        self.assertNotEqual(repeated[0]['source_row'], repeated[1]['source_row'])
        self.assertTrue(all(len(r['raw']) == 34 for r in records))
        self.assertNotIn('Completed', summary['states'])

    def test_berth_not_eta_selects_clearing(self):
        rows, _ = preview_csv(report({6: '10-Oct-26'}, {7: '10-Oct-26'}))
        self.assertEqual(rows[0]['proposed_state'], 'Awaiting arrival')
        self.assertEqual(rows[1]['proposed_state'], 'In clearing')

    def test_dated_ecd_does_not_invent_delivery_date_or_completion(self):
        rows, _ = preview_csv(report({26: 'RECEIVED 10 Oct 2024'}))
        r = rows[0]
        self.assertEqual(r['proposed_state'], 'Delivered')
        self.assertIsNone(r['dates']['warehouse'])
        self.assertIn('delivery_date_missing', {i['code'] for i in r['issues']})

    def test_partial_comment_survives_factory_date(self):
        rows, _ = preview_csv(report({19: '10-Oct-26', 20: '11-Oct-26', 21: 'Delivery ongoing, balance 3 boxes'}))
        self.assertEqual(rows[0]['proposed_state'], 'In delivery')
        self.assertIsNone(rows[0]['pending_count'])
        self.assertIn('partial_delivery', {i['code'] for i in rows[0]['issues']})

    def test_release_dependencies_and_chronology(self):
        rows, _ = preview_csv(report({18: '10-Oct-26', 19: '9-Oct-26', 20: '8-Oct-26'}))
        codes = {i['code'] for i in rows[0]['issues']}
        self.assertIn('release_gap', codes)
        self.assertIn('chronology', codes)
        self.assertEqual(rows[0]['dates']['gate_out'], '2026-10-09')

    def test_ambiguous_dates_and_unconfirmed_labels_are_not_promoted(self):
        for raw in ('12 July 2024 & 01 Aug 2024', 'revd 5 Sept 2024', 'AEO', 'NA', '31-Feb-24'):
            self.assertIsNone(parse_date(raw)[0])
        self.assertEqual(parse_date('27-May-24')[0], '2024-05-27')

    def test_unknown_headers_rejected(self):
        with self.assertRaises(ValueError):
            preview_csv(b'BL,ETA\nABC,2026-10-10')

    def test_malformed_repeated_header_is_a_clear_import_error(self):
        content = report({}) + b'S/N,BOL NO\n'
        with self.assertRaisesRegex(ValueError, 'Column header'):
            preview_csv(content)

    def test_count_conflict_not_silently_repaired(self):
        rows, _ = preview_csv(report({8: '4', 9: '3x40'}))
        self.assertEqual(rows[0]['container_count'], 4)
        self.assertIn('count_conflict', {i['code'] for i in rows[0]['issues']})


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.sources = Path(self.temp.name) / 'sources'
        self.sources.mkdir()
        self.httpd = make_server(Path(self.temp.name) / 'db', 0, self.sources)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.httpd.server_address[1]
        self.cookie, self.csrf = '', ''

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()
        self.temp.cleanup()

    def call(self, method, path, body=None, headers=None, raw=None):
        con = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        h = {'Content-Type': 'application/json'}
        if self.cookie:
            h['Cookie'] = self.cookie
            h['X-CSRF-Token'] = self.csrf
        h.update(headers or {})
        data = raw if raw is not None else json.dumps(body).encode() if body is not None else None
        con.request(method, path, data, h)
        response = con.getresponse()
        status, result_headers, data = response.status, dict(response.getheaders()), response.read()
        con.close()
        try:
            data = json.loads(data)
        except (ValueError, UnicodeDecodeError):
            pass
        return status, data, result_headers

    def owner(self):
        status, result, headers = self.call('POST', '/api/auth/setup', {'password': 'only-a-test-password'})
        self.assertEqual(status, 200, result)
        self.cookie = headers['Set-Cookie'].split(';')[0]
        self.csrf = result['csrf']

    def preview(self, content=None):
        return self.call('POST', '/api/imports/preview', {'client_id': 1, 'filename': 'test.csv',
            'content_base64': base64.b64encode(content or report({26: '10-Oct-26'})).decode()})

    def test_authentication_csrf_and_cross_origin(self):
        self.assertEqual(self.call('GET', '/api/shipments')[0], 401)
        self.owner()
        self.assertEqual(self.call('GET', '/api/shipments')[0], 200)
        self.assertEqual(self.call('POST', '/api/clients', {'name': 'New client'}, {'X-CSRF-Token': 'bad'})[0], 403)
        self.assertEqual(self.call('POST', '/api/clients', {'name': 'New client'}, {'Origin': 'https://attacker.invalid'})[0], 403)
        self.assertEqual(self.call('GET', '/api/clients', headers={'Host':'attacker.invalid:'+str(self.port)})[0], 403)
        self.assertEqual(self.call('POST', '/api/auth/setup', {'password': 'another-test-password'})[0], 409)

    def test_preview_apply_idempotency_and_persistence(self):
        self.owner()
        status, result, _ = self.preview()
        self.assertEqual(status, 200, result)
        batch = result['batch']['id']
        self.assertEqual(self.call('GET', '/api/shipments')[1]['total'], 0)
        self.assertEqual(self.preview()[1]['batch']['id'], batch)
        self.assertEqual(self.call('POST', f'/api/imports/{batch}/apply', {})[0], 400)
        for _ in range(2):
            status, result, _ = self.call('POST', f'/api/imports/{batch}/apply', {'confirm_test_import': True})
            self.assertEqual(status, 200, result)
        self.assertEqual(self.call('GET', '/api/shipments')[1]['total'], 1)
        replacement = Application(self.httpd.app.store.directory, self.sources)
        with replacement.store.connect() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM shipments').fetchone()[0], 1)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM audit WHERE action='test_import_applied'").fetchone()[0], 1)
        self.assertEqual(self.call('GET', '/api/imports')[1]['imports'][0]['status'], 'applied')

    def test_client_creation_case_insensitive_uniqueness_and_scoping(self):
        self.owner()
        self.assertEqual(self.call('POST', '/api/clients', {'name':'Nestle'})[0], 200)
        self.assertEqual(self.call('POST', '/api/clients', {'name':'nestle'})[0], 409)
        batch = self.preview()[1]['batch']['id']
        self.call('POST', f'/api/imports/{batch}/apply', {'confirm_test_import':True})
        self.assertEqual(self.call('GET','/api/shipments?client_id=2')[1]['total'], 0)
        self.assertEqual(self.call('GET','/api/shipments?search=BL1')[1]['total'], 1)
        self.assertEqual(self.call('GET','/api/shipments?state=Completed')[1]['total'], 0)

    def test_gzi_mapping_cannot_be_silently_applied_to_dangote(self):
        self.owner()
        status, _, _ = self.call('POST','/api/imports/preview', {'client_id':2,'filename':'test.csv',
            'content_base64':base64.b64encode(report({})).decode()})
        self.assertEqual(status, 422)

    def test_refusals_file_boundaries_and_no_content_execution(self):
        self.owner()
        for path in ('/data/libra-test.sqlite3','/imports/test.csv','/../docs/decisions.md','/api/shipments/../../etc/passwd'):
            self.assertEqual(self.call('GET',path)[0], 404)
        self.assertEqual(self.call('POST','/api/clients',raw=b'{broken')[0], 400)
        self.assertEqual(self.call('POST','/api/clients',raw=b'[]')[0], 400)
        self.assertEqual(self.call('DELETE','/api/clients')[0], 405)
        self.assertEqual(self.call('GET','/api/shipments?limit=banana')[0], 400)
        self.assertEqual(self.call('GET','/api/shipments?state=Unknown')[0], 400)
        self.assertEqual(self.call('POST','/api/imports/preview',{'source_id':'../../etc/passwd','client_id':1})[0], 404)
        self.assertEqual(self.call('POST','/api/clients',{},headers={'Content-Length':str(9*1024*1024)})[0],413)
        self.assertEqual(self.call('POST','/api/clients',{},headers={'Content-Type':'text/plain'})[0],415)

    def test_changed_cutoff_does_not_silently_replace_existing_preview(self):
        self.owner()
        first = self.preview()[1]['batch']['id']
        status, _, _ = self.call('POST','/api/imports/preview', {'client_id':1,'filename':'test.csv',
            'report_date':'2026-10-26','content_base64':base64.b64encode(report({26:'10-Oct-26'})).decode()})
        self.assertEqual(status,409)
        batch = self.call('GET','/api/imports/'+first)[1]['batch']
        self.assertIsNone(batch['report_date'])

    def test_logout_revokes_session(self):
        self.owner()
        self.assertEqual(self.call('POST','/api/auth/logout',{})[0],200)
        self.assertEqual(self.call('GET','/api/shipments')[0],401)

    def test_known_source_can_be_staged_and_applied_without_exposing_original(self):
        if not SOURCE.exists():
            self.skipTest('Private GZI source not supplied')
        self.owner()
        content = SOURCE.read_bytes()
        status, result, _ = self.preview(content)
        self.assertEqual(status, 200, result)
        batch = result['batch']['id']
        self.assertEqual(result['batch']['summary']['shipments'], 220)
        self.assertEqual(self.call('POST', f'/api/imports/{batch}/apply', {'confirm_test_import':True})[0], 200)
        overview = self.call('GET', '/api/overview')[1]
        self.assertEqual(overview['total'], 220)
        self.assertEqual(overview['states']['Completed'], 0)
        self.assertEqual(overview['notifications'], 'disabled')
        first = self.call('GET', '/api/shipments')[1]['shipments'][0]
        detail = self.call('GET', f"/api/shipments/{first['id']}")[1]['shipment']
        self.assertEqual(len(detail['raw']), 34)
        self.assertEqual([e['action'] for e in detail['history']], ['import_preview_created','test_import_applied'])
        original = self.httpd.app.store.directory/'originals'/(hashlib.sha256(content).hexdigest()+'.csv')
        self.assertEqual(original.read_bytes(), content)


if __name__ == '__main__':
    unittest.main()
