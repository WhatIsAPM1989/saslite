"""Project detection follows editor settings and never evaluates Run commands."""
import json
import tempfile
import unittest
from pathlib import Path

from saslite.gui.project_profiles import expected_profile
from saslite.profiles import load_profile_file

try:
    from saslite.gui.app import app
except ModuleNotFoundError as exc:
    if exc.name != 'flask':
        raise
    app = None


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve() / 'Project with spaces'
        (self.root / 'programs').mkdir(parents=True)
        self.program = self.root / 'programs' / 'analysis.sas'
        self.program.write_text('data result; value=1; run;')
        (self.root / '_local/config/metadata').mkdir(parents=True)
        (self.root / 'saslite-project.json').write_text('{"version": 1}')

    def tearDown(self):
        self.tmp.cleanup()

    def settings(self, command):
        folder = self.root / '.vscode'
        folder.mkdir(exist_ok=True)
        (folder / 'settings.json').write_text(json.dumps({
            'code-runner.executorMapByFileExtension': {'.sas': command}}))

    def test_runner_profile_and_root_with_spaces(self):
        profile = self.root.parent / 'shared.py'
        profile.write_text('raise RuntimeError("discovery must not import me")')
        self.settings('"$workspaceRoot/runner" --profile-file "$workspaceRoot/../shared.py" '
                      '--profile-root "$workspaceRoot" $fullFileName')
        result = expected_profile(str(self.program), {})
        self.assertEqual(result['settings']['profile_file'], str(profile))
        self.assertEqual(result['settings']['profile_root'], str(self.root))
        self.assertTrue(result['exists'])
        self.assertFalse(result['matches'])
        self.assertTrue(expected_profile(str(self.program), dict(name='demo', **result['settings']))['matches'])
        self.assertFalse(expected_profile(str(self.program), dict(name='demo', profile_file=str(profile),
                         profile_root=str(self.root.parent)))['matches'])

    def test_conventional_profile_template_is_executable(self):
        result = expected_profile(str(self.program), {})
        self.assertEqual(result['project_root'], str(self.root))
        self.assertFalse(result['exists'])
        target = Path(result['settings']['profile_file'])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(result['template'])
        profile = load_profile_file(target, project_root=str(self.root))
        code = '%unknown();'
        self.assertEqual(profile.prepare_source(code, source_name=str(self.program)), code)
        (target.parent / 'localsetup.sas').write_text('%let project_ready=1;')
        self.assertIn('localsetup.sas', profile.prepare_source(code, source_name=str(self.program)))

    def test_jsonc_and_equals_flags(self):
        self.settings('run --profile=example --profile-root="${workspaceFolder}"')
        path = self.root / '.vscode/settings.json'
        path.write_text('// comment\n' + path.read_text()[:-1] + ', /* tail */ }')
        result = expected_profile(str(self.program), {})
        self.assertEqual(result['settings']['profile'], 'example')
        self.assertTrue(result['exists'])

    def test_unresolved_variables_not_guessed(self):
        self.settings('run --profile-file "$UNKNOWN/profile.py"')
        with self.assertRaises(ValueError):
            expected_profile(str(self.program), {})

    def test_manual_profile_in_same_project_accepted(self):
        self.assertTrue(expected_profile(str(self.program), {
            'name': 'custom', 'profile_root': str(self.root), 'profile_file': '/custom.py'})['matches'])


@unittest.skipIf(app is None, 'GUI extra not installed')
class DiscoveryApiTests(DiscoveryTests):
    def setUp(self):
        super().setUp()
        self.saved = app.config.copy()
        self.client = app.test_client()
        self.headers = {'X-SASLite-Token': app.config['SAS_API_TOKEN']}

    def tearDown(self):
        app.config.clear()
        app.config.update(self.saved)
        super().tearDown()

    def post(self, endpoint, body):
        return self.client.post(endpoint, json=body, headers=self.headers)

    def test_open_create_connect_execute_and_no_overwrite(self):
        result = self.post('/api/open-file', {'path': str(self.program)}).get_json()
        self.assertTrue(result['success'])
        self.assertEqual(result['path'], str(self.program))
        expected = result['recommendation']
        target = Path(expected['settings']['profile_file'])
        self.assertFalse(target.exists())
        body = dict(path=str(self.program), create=True, expected_profile_file=str(target))
        self.assertEqual(self.client.post('/api/program-profile', json=body).status_code, 403)
        created = self.post('/api/program-profile', body)
        self.assertEqual(created.status_code, 200, created.get_json())
        original = target.read_bytes()
        self.assertEqual(self.post('/api/program-profile', body).status_code, 409)
        self.assertEqual(target.read_bytes(), original)
        connected = self.post('/api/profile', created.get_json()['recommendation']['settings']).get_json()
        self.assertTrue(connected['success'], connected)
        self.assertTrue(self.post('/api/open-file', {'path': str(self.program)}).get_json()['recommendation']['matches'])
        included = self.program.parent / 'included.sas'
        included.write_text('data included; x=2; run;')
        execution = self.post('/api/execute', {'code': '%include "included.sas";', 'source_path': str(self.program)})
        self.assertTrue(execution.get_json()['success'], execution.get_json())

    def test_creation_rejects_stale_path(self):
        response = self.post('/api/program-profile', dict(path=str(self.program), create=True,
                             expected_profile_file='/wrong/path.py'))
        self.assertEqual(response.status_code, 409)
        self.assertFalse((self.root / '_local/config/saslite_profile.py').exists())

    def test_local_picker_keeps_paths(self):
        result = self.post('/api/program-files', {'directory': str(self.program.parent)}).get_json()
        self.assertEqual(result['entries'][0]['path'], str(self.program))
        self.assertEqual(self.client.post('/api/program-files', json={}).status_code, 403)
