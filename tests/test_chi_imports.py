"""Owner-confirmed CHI headings stay separate from other client mappings."""
import base64
import csv
import io
import os
import unittest
from pathlib import Path
import uuid

from test_application import HttpFixture
from imports import preview_csv

HEADERS=['S/N','PRE-ALERT DATE','CLIENT REF','BOL/AWB NO','DESCRIPTION','SUPPLIER','MODE','LINER','ETA','ATA',
         'CLEARING TYPE','PAAR Recd Date','OBL Recd Date','REGULATING AGENCY','COUNT COUNT ','KG/SIZE','Terminal',
         'Ass Date','C Number','Duty Pay Date','Custom Exam Date','Shipping Release Date','Custom Rel. Date',
         'TDO / Exit Note Date','COMMENT','AGENT','ECD']


def chi(**changes):
    values={'S/N':'1','BOL/AWB NO':'CHI-QA-1','DESCRIPTION':'Synthetic cargo','MODE':'SEA','COUNT COUNT ':'2',
            'KG/SIZE':'40','ATA':'20-Oct-26','Duty Pay Date':'21-Oct-26','TDO / Exit Note Date':'23-Oct-26',
            'Shipping Release Date':'22-Oct-26','AGENT':'QA agent',**changes}
    stream=io.StringIO();writer=csv.writer(stream)
    writer.writerow(['Shipments in clearing']);writer.writerow(HEADERS)
    writer.writerow([values.get(h,'') for h in HEADERS])
    return stream.getvalue().encode()


class CHIMappingTests(unittest.TestCase):
    def test_owner_confirmed_container_receipt_and_sea_release_meanings(self):
        raw=chi()
        rows,summary=preview_csv(raw,profile='CHI');job=rows[0]
        self.assertEqual(job['container_count'],2)
        self.assertEqual(job['container_size'],'40')
        self.assertEqual(job['dates']['duty_receipt'],'2026-10-21')
        self.assertEqual(job['dates']['berth'],'2026-10-20')
        self.assertEqual(job['dates']['tdo'],'2026-10-23')
        self.assertEqual(job['handler'],'QA agent')
        self.assertEqual(job['transport_mode'],'SEA')
        self.assertIsNone(job['dates']['warehouse'])
        self.assertEqual(job['source_headers'],HEADERS)
        self.assertEqual(job['raw'][19],'21-Oct-26')
        self.assertEqual(summary['shipments'],1)

    def test_reordered_optional_columns_and_count_count_alias(self):
        rows,_=preview_csv(b'MODE,COUNT COUNT,BOL/AWB NO\nSEA,7,CHI-QA-2\n',profile='CHI')
        self.assertEqual(rows[0]['container_count'],7)
        self.assertIn('duty_receipt',rows[0]['missing_columns'])
        self.assertIsNone(rows[0]['dates']['duty_receipt'])

    def test_air_weight_and_exit_note_are_not_sea_quantities_or_tdo(self):
        rows,_=preview_csv(chi(MODE='AIR',**{'KG/SIZE':'40','COUNT COUNT ':'20'}),profile='CHI')
        job=rows[0]
        self.assertIsNone(job['container_count'])
        self.assertIsNone(job['container_size'])
        self.assertIsNone(job['dates']['berth'])
        self.assertIsNone(job['dates']['tdo'])
        self.assertEqual(job['dates']['duty_receipt'],'2026-10-21')
        self.assertEqual(job['report_details']['exit_note_date_reported'],'2026-10-23')
        self.assertEqual(job['report_details']['kg_size_raw'],'40')
        self.assertIn('transport_mode_review',{i['code'] for i in job['issues']})

    def test_unknown_mode_does_not_assume_sea(self):
        rows,_=preview_csv(chi(MODE=''),profile='CHI')
        self.assertIsNone(rows[0]['dates']['tdo'])
        self.assertIsNone(rows[0]['dates']['berth'])
        self.assertIsNone(rows[0]['container_count'])

    def test_ambiguous_count_headings_and_bad_dates_stay_pending(self):
        rows,_=preview_csv(b'BOL/AWB NO,MODE,COUNT COUNT,CONT COUNT,Duty Pay Date\nCHI-QA,SEA,2,3,not a date\n',profile='CHI')
        job=rows[0]
        self.assertIsNone(job['container_count'])
        self.assertIsNone(job['dates']['duty_receipt'])
        self.assertIn('duty_receipt',job['unresolved_fields'])
        self.assertIn('container_count',job['missing_columns'])
        self.assertEqual(job['raw'][2:4],['2','3'])

    def test_chi_aliases_do_not_silently_expand_gzi_profile(self):
        with self.assertRaises(ValueError):preview_csv(chi())
        with self.assertRaises(ValueError):preview_csv(chi(),profile='UNKNOWN')

    def test_private_chi_source_if_supplied(self):
        fixture=os.environ.get('LIBRA_CHI_FIXTURE')
        if not fixture or not Path(fixture).is_file():self.skipTest('Private CHI fixture not supplied')
        rows,summary=preview_csv(Path(fixture).read_bytes(),profile='CHI')
        self.assertEqual((len(rows),summary['unique_bls']),(5,5))
        self.assertTrue(all(r['transport_mode']=='SEA' for r in rows))
        self.assertEqual([r['container_count'] for r in rows],[2,1,1,20,1])
        self.assertEqual(sum(bool(r['dates']['duty_receipt']) for r in rows),4)
        self.assertEqual(sum(bool(r['dates']['tdo']) for r in rows),3)
        self.assertTrue(all(len(r['raw'])==27 and len(r['source_headers'])==27 for r in rows))


class CHIApiTests(HttpFixture):
    def setUp(self):
        super().setUp();self.owner()

    def stage(self, raw, client=3):
        return self.call('POST','/api/imports/preview',{'client_id':client,'filename':'chi-qa.csv',
            'content_base64':base64.b64encode(raw).decode()})

    def sync(self,batch):
        reviewed=self.call('GET','/api/imports/'+batch+'/review-updates')[1]['review']
        status,result,_=self.call('POST','/api/imports/'+batch+'/review-updates',{'confirm_test_import':True,
            'command_id':uuid.uuid4().hex,'plan_token':reviewed['token'],'reason':'Reviewed CHI test report'})
        self.assertEqual(status,200,result)
        return result

    def test_chi_preview_apply_receipt_and_originals(self):
        status,result,_=self.stage(chi())
        self.assertEqual(status,200,result)
        batch=result['batch'];self.assertEqual(batch['mapping'],'chi-header-v1')
        self.assertEqual(self.call('GET','/api/shipments')[1]['total'],0)
        self.assertEqual(self.stage(chi())[1]['batch']['id'],batch['id'])
        self.sync(batch['id'])
        job=self.call('GET','/api/shipments')[1]['shipments'][0]
        detail=self.call('GET','/api/shipments/'+str(job['id']))[1]['shipment']
        self.assertEqual(detail['client_name'],'CHI')
        self.assertEqual(detail['dates']['duty_receipt'],'2026-10-21')
        self.assertEqual(detail['field_agent'],'QA agent')
        self.assertTrue(all(i['payment']=='unknown' for i in detail['operation']['invoices'].values()))
        self.assertEqual(detail['source_snapshot']['source_headers'],HEADERS)
        self.assertEqual(self.call('GET','/api/shipments?client_id=1')[1]['total'],0)

    def test_chi_updates_same_job_and_other_clients_stay_separate(self):
        raw=chi()
        batch=self.stage(raw)[1]['batch']['id'];self.sync(batch)
        job=self.call('GET','/api/shipments')[1]['shipments'][0]
        original=self.call('GET','/api/shipments/'+str(job['id']))[1]['shipment']['source_snapshot']
        update=self.stage(chi(DESCRIPTION='Revised CHI cargo'))[1]['batch']['id'];self.sync(update)
        self.assertEqual(self.call('GET','/api/shipments')[1]['total'],1)
        saved=self.call('GET','/api/shipments/'+str(job['id']))[1]['shipment']
        self.assertEqual(saved['description'],'Revised CHI cargo')
        self.assertEqual(saved['source_snapshot'],original)
        self.assertEqual(len(saved['report_history']),1)
        gzi=self.stage(b'BL,DESCRIPTION\nCHI-QA-1,Different client job\n',1)[1]['batch']['id'];self.sync(gzi)
        self.assertEqual(self.call('GET','/api/shipments')[1]['total'],2)
        self.assertEqual(self.call('GET','/api/shipments?client_id=3')[1]['total'],1)

    def test_unreviewed_clients_still_rejected(self):
        self.assertEqual(self.stage(chi(),2)[0],422)
