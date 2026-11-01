"""Offline tests: old PG settings are read without database mutation."""
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

backend = module(ROOT / 'backend' / 'workplace_pg' / 'settings_backend.py', 'jobiew_pg_under_test')
reconnect = module(ROOT / 'scripts' / 'reconnect_existing_postgres.py', 'jobiew_reconnect_under_test')

class ExistingPostgresTests(unittest.TestCase):
    def config(self, base):
        f = Path(base, 'data', 'postgres_local.json')
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({'database':'old_company_db','user':'old_user','password':'superprivate',
                                 'host':'127.0.0.1','port':5432}), encoding='utf-8')
        return f

    def test_old_postgres_config_is_not_sqlite(self):
        with tempfile.TemporaryDirectory() as base:
            self.config(base)
            with patch.dict(os.environ, {'WI_DB_ENGINE':'postgresql', 'DJANGO_DEBUG':'1'}, clear=True):
                result = backend.resolve_database(base)
            self.assertEqual(result['ENGINE'],'django.db.backends.postgresql')
            self.assertEqual(result['NAME'],'old_company_db')
            self.assertEqual(result['PASSWORD'],'superprivate')

    def test_production_does_not_automatically_use_private_file(self):
        with tempfile.TemporaryDirectory() as base:
            self.config(base)
            with patch.dict(os.environ, {'WI_DB_ENGINE':'postgresql','DJANGO_DEBUG':'0'}, clear=True):
                with self.assertRaises(RuntimeError):
                    backend.resolve_database(base)

    def test_production_env_connects_to_postgres(self):
        with tempfile.TemporaryDirectory() as base:
            with patch.dict(os.environ, {'DJANGO_DEBUG':'0', 'WI_DB_ENGINE':'postgresql',
                                         'WI_DB_NAME':'server_db','WI_DB_USER':'server_user'}, clear=True):
                result=backend.resolve_database(base)
            self.assertEqual(result['NAME'],'server_db')

    def test_existing_sqlite_option_still_requires_development(self):
        with tempfile.TemporaryDirectory() as base:
            with patch.dict(os.environ, {'WI_DB_ENGINE':'sqlite','DJANGO_DEBUG':'0'}, clear=True):
                with self.assertRaises(RuntimeError):
                    backend.resolve_database(base)

    def test_no_secrets_are_embedded_in_root_env(self):
        with tempfile.TemporaryDirectory() as base:
            f = self.config(base)
            root = Path(base, 'new')
            root.mkdir()
            (root/'backend').mkdir()
            (root/'backend'/'data').mkdir()
            (root/'.env.local').write_text('DJANGO_DEBUG=1\nWI_DB_ENGINE=sqlite\nOTHER_SETTING=keep\n', encoding='utf-8')
            reconnect.configure(root,f,reconnect.parse_private_config(f))
            content=(root/'.env.local').read_text(encoding='utf-8')
            self.assertIn('WI_DB_ENGINE=postgresql',content)
            self.assertNotIn('WI_DB_ENGINE=sqlite',content)
            self.assertNotIn('superprivate',content)
            self.assertIn('OTHER_SETTING=keep',content)
            self.assertEqual((root/'backend'/'data'/'postgres_local.json').read_bytes(),f.read_bytes())

    def test_find_old_project_at_expected_location(self):
        with tempfile.TemporaryDirectory() as base:
            project=Path(base,'Jobiew');project.mkdir()
            expected=Path(base,'TestProject','workplace_insights','data','postgres_local.json')
            expected.parent.mkdir(parents=True)
            expected.write_text('{}')
            self.assertEqual(reconnect.discover_sources(project),expected)

    def test_bad_config_does_not_get_accepted(self):
        with tempfile.TemporaryDirectory() as base:
            f=Path(base,'postgres_local.json')
            f.write_text('{"database":"x","user":"y","password":""}')
            with self.assertRaises(RuntimeError):
                reconnect.parse_private_config(f)

    def test_different_explicit_pg_vars_win(self):
        with tempfile.TemporaryDirectory() as base:
            self.config(base)
            with patch.dict(os.environ, {'WI_DB_ENGINE':'postgresql','DJANGO_DEBUG':'1',
                                         'WI_DB_NAME':'explicit','WI_DB_USER':'account'},clear=True):
                result=backend.resolve_database(base)
            self.assertEqual(result['NAME'],'explicit')

if __name__=='__main__': unittest.main()
