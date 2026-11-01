"""Offline regression for local Windows startup without importing Django."""
from pathlib import Path
import importlib.util
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('jobiew_manage_under_test', ROOT / 'backend' / 'manage.py')
manage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manage)


class LocalStartupTests(unittest.TestCase):
    def test_windows_local_runserver_defaults_are_safe(self):
        env = {}
        with tempfile.TemporaryDirectory() as root:
            manage.configure_local_environment(['manage.py', 'runserver', '8000'], env, 'nt', root)
        self.assertEqual(env['DJANGO_DEBUG'], '1')
        self.assertEqual(env['WI_DB_ENGINE'], 'sqlite')

    def test_nonlocal_bind_never_sets_debug(self):
        for address in ('0.0.0.0:8000', '192.168.1.12:8000', '[::]:8000'):
            env = {}
            with tempfile.TemporaryDirectory() as root:
                manage.configure_local_environment(['manage.py','runserver', address], env, 'nt', root)
            self.assertNotIn('DJANGO_DEBUG', env)
            self.assertNotIn('WI_DB_ENGINE', env)

    def test_linux_never_autoconfigures(self):
        env = {}
        with tempfile.TemporaryDirectory() as root:
            manage.configure_local_environment(['manage.py','runserver','8000'], env, 'posix', root)
        self.assertFalse(env)

    def test_explicit_production_is_not_weakened(self):
        env = {'DJANGO_DEBUG':'0', 'WI_DB_ENGINE':'postgresql', 'WI_DB_NAME':'jobiew', 'WI_DB_USER':'srv'}
        with tempfile.TemporaryDirectory() as root:
            manage.configure_local_environment(['manage.py','runserver','8000'], env, 'nt', root)
        self.assertEqual(env['DJANGO_DEBUG'], '0')
        self.assertEqual(env['WI_DB_ENGINE'], 'postgresql')
        self.assertNotIn('DJANGO_SECRET_KEY', env)

    def test_postgres_variables_not_switched_to_sqlite(self):
        env = {'WI_DB_NAME':'existing', 'WI_DB_USER':'developer'}
        with tempfile.TemporaryDirectory() as root:
            manage.configure_local_environment(['manage.py','runserver','8000'], env, 'nt', root)
        self.assertEqual(env['DJANGO_DEBUG'], '1')
        self.assertNotIn('WI_DB_ENGINE', env)

    def test_env_file_never_overrides_external_env(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root,'.env.local').write_text('DJANGO_DEBUG=1\nWI_DB_ENGINE=sqlite\nWI_DB_PASSWORD="fromfile"\n', encoding='utf-8')
            env={'DJANGO_DEBUG':'0'}
            manage.configure_local_environment(['manage.py','runserver','8000'], env, 'nt', root)
        self.assertEqual(env['DJANGO_DEBUG'],'0')
        self.assertEqual(env['WI_DB_PASSWORD'],'fromfile')

    def test_ignores_unrecognized_env_fields(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root,'.env.local').write_text('LD_PRELOAD=danger\nDJANGO_DEBUG=1\n', encoding='utf-8')
            env={}
            manage.configure_local_environment(['manage.py','runserver','8000'], env, 'nt', root)
        self.assertNotIn('LD_PRELOAD',env)
        self.assertEqual(env['DJANGO_DEBUG'],'1')

if __name__ == '__main__': unittest.main()
