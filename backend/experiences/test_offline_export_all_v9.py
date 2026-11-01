"""Tests for ALL remaining offline export helpers (no DB required)."""
import hashlib
import json
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile
from django.test import SimpleTestCase
from experiences.offline_export_all_core_v9 import BatchArchive, make_private_record


class AllRemainingExportTests(SimpleTestCase):
    def sample(self, pk):
        return SimpleNamespace(
            pk=pk, source_url=f'https://example.invalid/experiences/{pk}', content_sha256='a'*64,
            company_id=21, company=SimpleNamespace(display_name='شرکت نمونه'),
            body='کار خوب بود، تماس 09123456789', title='گزارش', job_title='توسعه‌دهنده',
            published_jalali='', employment_period_jalali='', source_kind='work',
            pros=['آموزش'], cons=['ترافیک'], copyright_review='unknown',
            company_attribution_status='unverified', independence_status='unknown'
        )

    def test_masks_contacts_but_keeps_source_hash_and_company(self):
        obj=self.sample(9)
        rec, changed=make_private_record(obj)
        self.assertTrue(changed)
        self.assertNotIn('09123456789',rec['body'])
        self.assertEqual(rec['source_content_sha256'],'a'*64)
        self.assertEqual(rec['company_id'],'21')
        self.assertEqual(rec['review_id'],'PG_9')
        self.assertIn('09123456789',obj.body)  # no source mutations

    def test_one_zip_many_batches_no_record_limit(self):
        buffer=BytesIO()
        with ZipFile(buffer,'w') as z:
            out=BatchArchive(z,batch_size=100)
            for i in range(1277):
                row,_=make_private_record(self.sample(i))
                out.append(row,False)
            m=out.complete({'already_five_v1':900}, 'five_v1')
        self.assertEqual(m['total_selected'],1277)
        self.assertEqual(len(m['files']),13)
        self.assertEqual(m['files'][-1]['records'],77)
        with ZipFile(BytesIO(buffer.getvalue())) as z:
            self.assertIsNone(z.testzip())
            self.assertEqual(sum(e['records'] for e in m['files']),1277)
            for e in m['files']:
                self.assertEqual(hashlib.sha256(z.read(e['name'])).hexdigest(),e['sha256'])
            self.assertEqual(json.loads(z.read('manifest.json'))['total_selected'],1277)

    def test_no_empty_jsonl_batch(self):
        buffer=BytesIO()
        with ZipFile(buffer,'w') as z:
            out=BatchArchive(z,batch_size=100)
            for i in range(200):
                row,_=make_private_record(self.sample(i))
                out.append(row,False)
            m=out.complete({},'five_v1')
        self.assertEqual(len(m['files']),2)
        self.assertEqual(m['files'][-1]['records'],100)

    def test_rejects_bad_batch_size(self):
        with ZipFile(BytesIO(),'w') as z:
            with self.assertRaises(ValueError):
                BatchArchive(z, batch_size=501)
