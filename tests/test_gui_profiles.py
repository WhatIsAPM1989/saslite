"""GUI sessions must apply profiles and survive rejected profile changes."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from saslite.gui.app import app, main
except ModuleNotFoundError as exc:
    if exc.name != 'flask':
        raise
    app = None


@unittest.skipIf(app is None, 'GUI extra not installed')
class GuiProfileTests(unittest.TestCase):
    def setUp(self):
        self.saved = app.config.copy()
        self.client = app.test_client()
        self.headers = {'X-SASLite-Token': app.config['SAS_API_TOKEN']}
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.profile = self.root / 'profile.py'
        self.profile.write_text('''from saslite.profiles.base import CompatibilityProfile
class Demo(CompatibilityProfile):
    name = 'demo'
    def prepare_source(self, source, *, source_name):
        return source.replace('%setup();', 'data ready; value=42; run;')
def create_profile(*, project_root=None):
    return Demo()
''')

    def tearDown(self):
        app.config.clear()
        app.config.update(self.saved)
        self.tmp.cleanup()

    def connect(self, **overrides):
        settings = dict(profile_file=str(self.profile), profile_root=str(self.root))
        settings.update(overrides)
        return self.client.post('/api/profile', json=settings, headers=self.headers)

    def test_profile_executes_and_disconnect_clears_work(self):
        self.assertEqual(self.connect().status_code, 200)
        state = self.client.get('/api/profile').get_json()
        self.assertEqual(state['name'], 'demo')
        self.assertEqual(state['profile_root'], str(self.root.resolve()))
        result = self.client.post('/api/execute', json={'code': '%setup();'}, headers=self.headers)
        self.assertTrue(result.get_json()['success'], result.get_json())
        self.assertEqual(app.config['SAS_SESSION'].get_dataset('WORK', 'READY').iloc[0]['value'], 42)
        response = self.client.post('/api/profile', json={}, headers=self.headers)
        self.assertIsNone(response.get_json()['profile']['name'])
        self.assertFalse(app.config['SAS_SESSION'].session.dataset_exists('WORK', 'READY'))

    def test_bad_profile_preserves_session_and_active_state(self):
        self.connect()
        session = app.config['SAS_SESSION']
        for change in ({'profile_file': str(self.root / 'missing.py')},
                       {'profile_root': str(self.root / 'missing')},
                       {'profile': 'example'}, {'profile_root': 123}):
            self.assertEqual(self.connect(**change).status_code, 400)
            self.assertIs(app.config['SAS_SESSION'], session)
            self.assertEqual(self.client.get('/api/profile').get_json()['name'], 'demo')

    def test_mutation_requires_token(self):
        self.assertEqual(self.client.post('/api/profile', json={}).status_code, 403)

    def test_cli_profile_is_visible(self):
        with patch('saslite.gui.app.app.run'), patch('saslite.gui.app.webbrowser.open'), \
                patch('saslite.gui.file_dialog.warm_macos_picker'):
            self.assertEqual(main(['--no-browser', '--profile-file', str(self.profile),
                                   '--profile-root', str(self.root)]), 0)
        self.assertEqual(self.client.get('/api/profile').get_json()['name'], 'demo')

    def test_edit_source_save_and_apply(self):
        self.connect()
        session = app.config['SAS_SESSION']
        source = self.client.get('/api/profile/source').get_json()
        self.assertEqual(source['content'], self.profile.read_text())
        source['content'] = source['content'].replace('value=42', 'value=73')
        saved = self.client.post('/api/profile/source', json=source, headers=self.headers)
        self.assertEqual(saved.status_code, 200, saved.get_json())
        self.assertIs(app.config['SAS_SESSION'], session)
        self.assertIn('value=73', self.profile.read_text())
        self.connect()
        self.client.post('/api/execute', json={'code': '%setup();'}, headers=self.headers)
        self.assertEqual(app.config['SAS_SESSION'].get_dataset('WORK', 'READY').iloc[0]['value'], 73)

    def test_source_rejects_syntax_errors_conflicts_and_missing_token(self):
        self.connect()
        original = self.profile.read_bytes()
        source = self.client.get('/api/profile/source').get_json()
        self.assertEqual(self.client.post('/api/profile/source', json=source).status_code, 403)
        invalid = {**source, 'content': 'def broken('}
        self.assertEqual(self.client.post('/api/profile/source', json=invalid, headers=self.headers).status_code, 400)
        self.assertEqual(self.profile.read_bytes(), original)
        self.profile.write_bytes(original + b'\n# external edit\n')
        self.assertEqual(self.client.post('/api/profile/source', json=source, headers=self.headers).status_code, 409)
        self.assertTrue(self.profile.read_bytes().endswith(b'# external edit\n'))

    def test_source_without_profile_and_builtin(self):
        self.client.post('/api/profile', json={}, headers=self.headers)
        self.assertEqual(self.client.get('/api/profile/source').status_code, 400)
        self.connect(profile='example', profile_file=None)
        source = self.client.get('/api/profile/source').get_json()
        self.assertIn('class ExampleProfile', source['content'])
        self.assertFalse(source['editable'])
        self.assertEqual(self.client.post('/api/profile/source', json=source, headers=self.headers).status_code, 400)
