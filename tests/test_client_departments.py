"""Client organisation preserves shipment identities, imports and owner access."""
import base64
import json
import sqlite3
import tempfile
import uuid
import unittest
from pathlib import Path

from test_application import HttpFixture, report
from server import Application
from store import Store


class ClientDepartmentTests(HttpFixture):
    def setUp(self):
        super().setUp();self.owner()

    def client(self, ident):
        return next(c for c in self.call('GET','/api/clients?include_hidden=1')[1]['clients'] if c['id']==ident)

    def edit(self, ident, changes, expected=200, **extra):
        body={'revision':self.client(ident)['revision'],'command_id':uuid.uuid4().hex,'reason':'Owner directory update','changes':changes,**extra}
        status,result,_=self.call('POST',f'/api/clients/{ident}/update',body)
        self.assertEqual(status,expected,result)
        return result.get('client',result)

    def department(self,name='FMCG 2'):
        status,result,_=self.call('POST','/api/departments',{'name':name,'command_id':uuid.uuid4().hex,'reason':'New department'})
        self.assertEqual(status,200,result)
        return result['department']

    def job(self, client=1):
        status,result,_=self.call('POST','/api/shipments',{'client_id':client,'command_id':uuid.uuid4().hex,'reason':'Directory QA shipment',
            'changes':{'bl':'DIRECTORY-'+str(client),'container_count':2,'dates':{'paar':'2024-06-01'}}})
        self.assertEqual(status,200,result)
        return result['shipment']

    def test_initial_clients_and_new_clients_have_explicit_departments(self):
        departments=self.call('GET','/api/departments')[1]['departments']
        self.assertEqual(departments[0]['name'],'FMCG 1')
        clients=self.call('GET','/api/clients')[1]['clients']
        self.assertTrue(all(c['department_id']==departments[0]['id'] and not c['hidden'] for c in clients))
        self.assertEqual(self.client(1)['import_profile'],'gzi-header-v2')
        self.assertEqual(self.client(3)['import_profile'],'chi-header-v1')
        second=self.department()
        status,result,_=self.call('POST','/api/clients',{'name':'Synthetic client','department_id':second['id'],'notes':'Owner supplied notes'})
        self.assertEqual(status,200,result)
        self.assertEqual(result['client']['department_name'],'FMCG 2')
        self.assertIsNone(result['client']['import_profile'])

    def test_rename_keeps_ids_jobs_sources_mapping_and_survives_restart(self):
        batch=self.preview()[1]['batch']['id'];self.call('POST',f'/api/imports/{batch}/apply',{'confirm_test_import':True})
        job=self.call('GET','/api/shipments')[1]['shipments'][0]
        original=self.call('GET',f"/api/shipments/{job['id']}")[1]['shipment']['source_snapshot']
        saved=self.edit(1,{'name':'GZI Test Renamed','notes':'Client details'})
        self.assertEqual(saved['id'],1)
        self.assertEqual(saved['import_profile'],'gzi-header-v2')
        after=self.call('GET',f"/api/shipments/{job['id']}")[1]['shipment']
        self.assertEqual(after['client_name'],'GZI Test Renamed')
        self.assertEqual(after['source_snapshot'],original)
        status,result,_=self.preview(report({2:'New report after rename'}))
        self.assertEqual(status,200,result)
        Application(self.httpd.app.store.directory,self.sources)
        clients=self.call('GET','/api/clients?include_hidden=1')[1]['clients']
        self.assertEqual(len(clients),3)
        self.assertFalse(any(c['name']=='GZI' for c in clients))

    def test_department_reassignment_updates_scopes_without_rewriting_jobs(self):
        first=self.job();second_job=self.job(3);second=self.department()
        with self.httpd.app.store.connect() as con:
            before=con.execute('SELECT * FROM shipments ORDER BY id').fetchall()
            raw=con.execute('SELECT data FROM job_updates WHERE shipment_id=?',(second_job['id'],)).fetchone()[0]
        self.edit(3,{'department_id':second['id']})
        self.assertEqual(self.call('GET','/api/shipments?department_id=1')[1]['total'],1)
        self.assertEqual(self.call('GET',f"/api/overview?department_id={second['id']}")[1]['total'],1)
        actions=self.call('GET',f"/api/actions?department_id={second['id']}")[1]['actions']
        self.assertEqual({a['shipment_id'] for a in actions},{second_job['id']})
        self.assertEqual(self.call('GET','/api/shipments?department_id=1&client_id=3')[1]['total'],0)
        with self.httpd.app.store.connect() as con:
            self.assertEqual(con.execute('SELECT * FROM shipments ORDER BY id').fetchall(),before)
            self.assertEqual(con.execute('SELECT data FROM job_updates WHERE shipment_id=?',(second_job['id'],)).fetchone()[0],raw)

    def test_hide_and_restore_filter_workspace_but_keep_history(self):
        batch=self.preview()[1]['batch']['id'];self.call('POST',f'/api/imports/{batch}/apply',{'confirm_test_import':True})
        job=self.call('GET','/api/shipments')[1]['shipments'][0]
        self.edit(1,{'hidden':True})
        self.assertFalse(any(c['id']==1 for c in self.call('GET','/api/clients')[1]['clients']))
        self.assertTrue(self.client(1)['hidden'])
        self.assertEqual(self.call('GET','/api/overview')[1]['total'],0)
        self.assertEqual(self.call('GET','/api/shipments')[1]['total'],0)
        self.assertEqual(self.call('GET','/api/imports')[1]['imports'],[])
        self.assertEqual(self.call('GET','/api/shipments?include_hidden=1')[1]['total'],1)
        detail=self.call('GET',f"/api/shipments/{job['id']}")[1]['shipment']
        self.assertTrue(detail['client_hidden'])
        self.assertEqual(self.preview(report({2:'Do not stage hidden job'}))[0],409)
        self.assertEqual(self.call('POST','/api/shipments',{'client_id':1,'command_id':uuid.uuid4().hex,'reason':'Hidden new job','changes':{'bl':'HIDDEN'}})[0],409)
        self.edit(1,{'hidden':False})
        self.assertEqual(self.call('GET','/api/shipments')[1]['total'],1)
        self.assertEqual(self.call('GET','/api/imports')[1]['imports'][0]['id'],batch)

    def test_stale_client_edit_replay_and_audit(self):
        client=self.client(1)
        body={'revision':client['revision'],'command_id':uuid.uuid4().hex,'reason':'Correct display name','changes':{'name':'Updated display'}}
        route='/api/clients/1/update'
        first=self.call('POST',route,body)
        self.assertEqual(first[0],200,first[1])
        self.assertEqual(self.call('POST',route,body)[1],first[1])
        body['changes']['name']='Different body'
        self.assertEqual(self.call('POST',route,body)[0],409)
        body['command_id']=uuid.uuid4().hex
        self.assertEqual(self.call('POST',route,body)[0],409)
        with self.httpd.app.store.connect() as con:
            rows=con.execute("SELECT detail FROM audit WHERE action='client_updated'").fetchall()
            self.assertEqual(len(rows),1)
            audit=json.loads(rows[0][0]);self.assertEqual(audit['before']['name'],'GZI')
            self.assertEqual(audit['after']['name'],'Updated display')

    def test_invalid_names_visibility_departments_and_unknown_fields_rollback(self):
        for changes in ({'name':'CHI'},{'name':' '},{'hidden':'yes'},{'hidden':1},{'department_id':999},{'department_id':True},
                        {'import_profile':'chi-header-v1'},{'notes':'x'*2001}):
            status,_,_=self.call('POST','/api/clients/1/update',{'revision':1,'command_id':uuid.uuid4().hex,'reason':'Bad input','changes':changes})
            self.assertIn(status,(400,409))
        self.assertEqual(self.client(1)['revision'],1)
        self.assertEqual(self.client(1)['name'],'GZI')
        for route in ('/api/clients','/api/overview','/api/shipments','/api/actions','/api/imports'):
            self.assertEqual(self.call('GET',route+'?department_id=invalid')[0],400)
            self.assertEqual(self.call('GET',route+'?include_hidden=yes')[0],400)

    def test_authentication_csrf_and_department_uniqueness(self):
        self.assertEqual(self.call('POST','/api/departments',{'name':'FMCG 1'})[0],409)
        self.assertEqual(self.call('POST','/api/departments',{'name':'FMCG 2'},{'X-CSRF-Token':'wrong'})[0],403)
        cookie=self.cookie;self.cookie=''
        self.assertEqual(self.call('GET','/api/departments')[0],401)
        self.cookie=cookie
        self.assertIn(self.call('DELETE','/api/clients/1')[0],(404,405))

    def test_renamed_client_retains_its_own_profile_and_new_name_does_not_copy_it(self):
        self.edit(3,{'name':'Renamed CHI'})
        from test_chi_imports import chi
        payload={'client_id':3,'filename':'chi.csv','content_base64':base64.b64encode(chi()).decode()}
        self.assertEqual(self.call('POST','/api/imports/preview',payload)[1]['batch']['mapping'],'chi-header-v1')
        status,result,_=self.call('POST','/api/clients',{'name':'CHI'})
        self.assertEqual(status,200,result)
        self.assertIsNone(result['client']['import_profile'])
        payload['client_id']=result['client']['id']
        self.assertEqual(self.call('POST','/api/imports/preview',payload)[0],422)

    def test_client_changes_invalidate_report_reviews(self):
        batch=self.preview()[1]['batch']['id']
        plan=self.call('GET',f'/api/imports/{batch}/review-updates')[1]['review']
        self.edit(1,{'name':'Name changed after review'})
        self.assertEqual(self.call('POST',f'/api/imports/{batch}/review-updates',{'confirm_test_import':True,'plan_token':plan['token'],
            'command_id':uuid.uuid4().hex,'reason':'Old review'})[0],409)
        self.assertEqual(self.call('GET','/api/shipments')[1]['total'],0)

    def test_directory_creations_are_idempotent_with_command_ids(self):
        body={'name':'Idempotent department','command_id':uuid.uuid4().hex,'reason':'Owner created department'}
        first=self.call('POST','/api/departments',body)
        self.assertEqual(first[0],200,first[1])
        self.assertEqual(self.call('POST','/api/departments',body)[1],first[1])
        body['name']='Different department'
        self.assertEqual(self.call('POST','/api/departments',body)[0],409)
        payload={'name':'Idempotent client','department_id':first[1]['department']['id'],
                 'command_id':uuid.uuid4().hex,'reason':'Owner created client'}
        client=self.call('POST','/api/clients',payload)
        self.assertEqual(client[0],200,client[1])
        self.assertEqual(self.call('POST','/api/clients',payload)[1],client[1])

    def test_hidden_client_prevents_apply_on_both_import_routes(self):
        batch=self.preview()[1]['batch']['id']
        self.edit(1,{'hidden':True})
        self.assertEqual(self.call('POST',f'/api/imports/{batch}/apply',{'confirm_test_import':True})[0],409)
        plan=self.call('GET',f'/api/imports/{batch}/review-updates')[1]['review']
        self.assertEqual(self.call('POST',f'/api/imports/{batch}/review-updates',{'confirm_test_import':True,'plan_token':plan['token'],
            'command_id':uuid.uuid4().hex,'reason':'Hidden client'})[0],409)
        self.assertEqual(self.call('GET','/api/shipments?include_hidden=1')[1]['total'],0)


class DepartmentMigrationTests(unittest.TestCase):
    def test_v4_migration_preserves_clients_data_and_credentials_and_backs_up_once(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            with sqlite3.connect(store.path) as con:
                con.executescript('''PRAGMA foreign_keys=OFF;
                    CREATE TABLE clients_v4(id INTEGER PRIMARY KEY,name TEXT NOT NULL COLLATE NOCASE UNIQUE,created_at REAL NOT NULL);
                    INSERT INTO clients_v4 SELECT id,name,created_at FROM clients;
                    DROP TABLE clients;
                    ALTER TABLE clients_v4 RENAME TO clients;
                    DROP TABLE departments;
                    DELETE FROM migrations WHERE version=5;
                    INSERT INTO settings VALUES('migration-marker','test-only');
                    INSERT INTO shipments(id,client_id,created_at) VALUES(51,1,1);
                ''')
                before=con.execute('SELECT * FROM clients ORDER BY id').fetchall()
            Store(directory)
            with sqlite3.connect(store.path) as con:
                self.assertEqual(con.execute('SELECT id,name,created_at FROM clients ORDER BY id').fetchall(),before)
                self.assertEqual(con.execute('SELECT department_id FROM clients').fetchall(),[(1,),(1,),(1,)])
                self.assertEqual(con.execute("SELECT import_profile FROM clients WHERE id=1").fetchone()[0],'gzi-header-v2')
                self.assertEqual(con.execute("SELECT value FROM settings WHERE key='migration-marker'").fetchone()[0],'test-only')
                self.assertEqual(con.execute('SELECT client_id FROM shipments WHERE id=51').fetchone()[0],1)
            backups=list((Path(directory)/'backups').glob('*.sqlite3'))
            self.assertEqual(len(backups),1)
            with sqlite3.connect(backups[0]) as con:self.assertNotIn('department_id',{r[1] for r in con.execute('PRAGMA table_info(clients)')})
            Store(directory)
            self.assertEqual(len(list((Path(directory)/'backups').glob('*.sqlite3'))),1)
