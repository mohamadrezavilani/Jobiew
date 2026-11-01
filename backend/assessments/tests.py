import json,tempfile
from pathlib import Path
from io import StringIO
from django.test import TestCase
from django.core.management import call_command
from companies.models import Company
from experiences.models import PublicExperience
from .models import AiAssessment,AiDimension

class AiImportTests(TestCase):
    def test_import_never_publishes(self):
        c=Company.objects.create(id='c1',source_url='https://x.example/co',source_name='شرکت',display_name='شرکت')
        e=PublicExperience.objects.create(company=c,source_url='https://x.example/e',source_kind='work',title='نظر',body='نمونه',content_sha256='1')
        data={'source_url':e.source_url,'model':'test','timestamp_utc':'2026-10-19','result':{'dimensions':{'career_growth':{'score':9,'confidence':99,'evidence':[]}}}}
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'r.jsonl';p.write_text(json.dumps(data),encoding='utf8')
            for _ in range(2):call_command('import_ai_pilots',str(p),stdout=StringIO())
        self.assertEqual(AiAssessment.objects.count(),1)
        self.assertFalse(AiAssessment.objects.get().publish_approved)
        self.assertEqual(AiDimension.objects.get().semantic_status,'unreviewed')
