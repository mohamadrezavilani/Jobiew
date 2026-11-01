"""Offline pure QA for the five-criteria batch exporter."""
from django.test import SimpleTestCase
from experiences.offline_export_core_v8 import redact_contacts, choose_company_bundles

class OfflineExportV8Tests(SimpleTestCase):
    def test_contact_masking_and_non_contact(self):
        txt, changed = redact_contacts('شماره 09123456789 و ایمیل test@example.com')
        self.assertTrue(changed)
        self.assertNotIn('09123456789', txt)
        self.assertNotIn('test@example.com', txt)
        self.assertEqual(redact_contacts('فشار کاری مناسب'), ('فشار کاری مناسب', False))

    def test_multiples_of_same_company_selected(self):
        grouped = {'a':[{'pk':i,'source_url':f'a{i}'} for i in (1,3,2,4)],
                   'b':[{'pk':5,'source_url':'b5'}],
                   'c':[{'pk':6,'source_url':'c6'},{'pk':7,'source_url':'c7'}]}
        result = choose_company_bundles(grouped, limit=3, minimum_company_reviews=3, max_per_company=3)
        self.assertEqual([row['pk'] for row in result], [1,2,3])

    def test_already_imported_supports_min_company_count(self):
        grouped={'x':[{'pk':3,'source_url':'x3'}]}
        selected=choose_company_bundles(grouped,limit=2,minimum_company_reviews=3,max_per_company=5,
                                       already_count={'x':2})
        self.assertEqual(len(selected), 1)

    def test_bad_limits_rejected(self):
        with self.assertRaises(ValueError):
            choose_company_bundles({},limit=0,minimum_company_reviews=1,max_per_company=1)
