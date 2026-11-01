import importlib.util
import os
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from tempfile import TemporaryDirectory

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('jobiew_pipeline',ROOT/'scripts'/'run_ingest.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class PipelineTests(TestCase):
    def test_plan_has_crawler_then_sync_and_uses_one_sqlite(self):
        with patch.dict(os.environ,{'JOBIEW_CRAWL_MAX_ITEMS':'15','JOBIEW_CRAWL_MAX_REQUESTS':'30'}):
            plan=module.command_plan('crawl-and-sync',Path('/tmp/jobiew-test'))
        self.assertEqual(len(plan),2)
        self.assertIn('/tmp/jobiew-test/data/tajrobewiki.db',plan[0][0])
        self.assertIn('/tmp/jobiew-test/data/tajrobewiki.db',plan[1][0])
        self.assertIn('--apply',plan[1][0])
    def test_preview_does_not_apply(self):
        p=module.command_plan('preview',Path('/tmp/jobiew-test'))
        self.assertNotIn('--apply',p[0][0])
    def test_live_crawl_requires_explicit_permission(self):
        with TemporaryDirectory() as d:
            with patch.dict(os.environ,{'JOBIEW_RUNTIME_DIR':d,'WI_DB_ENGINE':'postgresql','JOBIEW_CRAWLER_PERMISSION_CONFIRMED':'0'}):
                self.assertEqual(module.main(['--mode','crawl-and-sync']),2)
                self.assertFalse((Path(d)/'data').exists())
    def test_refuse_non_postgres_server(self):
        with TemporaryDirectory() as d:
            with patch.dict(os.environ,{'JOBIEW_RUNTIME_DIR':d,'WI_DB_ENGINE':'sqlite'}):
                self.assertEqual(module.main(['--mode','sync-only']),2)
    def test_plan_no_db_or_network(self):
        with TemporaryDirectory() as d:
            with patch.dict(os.environ,{'JOBIEW_RUNTIME_DIR':d}):
                self.assertEqual(module.main(['--show-plan']),0)
                self.assertFalse((Path(d)/'data').exists())
