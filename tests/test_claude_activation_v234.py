"""Offline tests for the root-only Claude activation helper. No real credentials."""
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'enable_claude_six_v234.py'
spec = importlib.util.spec_from_file_location('enable_claude_six_v234', PATH)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class ClaudeActivationTests(unittest.TestCase):
    def test_preserves_other_config_and_replaces_duplicate_keys(self):
        old = ('WI_DB_PASSWORD=production-placeholder\n'
               '# keep this comment\n'
               'JOBIEW_CLAUDE_SIX_ENABLED=0\n'
               'export JOBIEW_CLAUDE_SIX_ENABLED=0\n'
               'ANTHROPIC_API_KEY=previous-placeholder\n'
               'OTHER_FLAG=safe\n')
        new = helper.render_env(old, {
            'ANTHROPIC_API_KEY': 'sk-ant-api-SYNTHETICONLY01234567890',
            'JOBIEW_CLAUDE_SIX_ENABLED': '1',
            'JOBIEW_CLAUDE_SIX_LIMIT': '20',
            'JOBIEW_CLAUDE_SIX_MODEL': 'claude-sonnet-5-5',
        })
        self.assertIn('WI_DB_PASSWORD=production-placeholder', new)
        self.assertIn('# keep this comment', new)
        self.assertIn('OTHER_FLAG=safe', new)
        self.assertEqual(new.count('JOBIEW_CLAUDE_SIX_ENABLED='), 1)
        self.assertNotIn('previous-placeholder', new)
        self.assertIn('JOBIEW_CLAUDE_SIX_LIMIT=20', new)
        self.assertIn('JOBIEW_CLAUDE_SIX_MODEL=claude-sonnet-5-5', new)

    def test_status_never_returns_secret(self):
        text = ('ANTHROPIC_API_KEY=sk-ant-api-SYNTHETICONLY01234567890\n'
                'JOBIEW_CLAUDE_SIX_ENABLED=1\n'
                'JOBIEW_CLAUDE_SIX_LIMIT=20\n')
        state = helper.read_env_flag_status(text)
        self.assertEqual(state['key_present'], 'yes')
        self.assertEqual(state['enabled'], '1')
        self.assertNotIn('SYNTHETICONLY', str(state))

    def test_idempotent_rendering(self):
        settings = {name: 'test' for name in helper.SETTINGS}
        once = helper.render_env('OTHER=VALUE\n', settings)
        self.assertEqual(helper.render_env(once, settings), once)

    def test_model_and_key_format(self):
        self.assertTrue(helper.KEY_PATTERN.fullmatch('sk-ant-usr-' + 'x' * 30))
        self.assertTrue(helper.MODEL_PATTERN.fullmatch('claude-sonnet-5-5'))
        self.assertFalse(helper.KEY_PATTERN.fullmatch('invalid'))
        self.assertFalse(helper.KEY_PATTERN.fullmatch('sk-ant-usr-\nINVALID'))


if __name__ == '__main__':
    unittest.main()
