"""Exercise schema policies through the GUI API and its log renderer."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import pandas as pd

from saslite import SasInterpreter
from saslite.storage.memory import MemoryBackend

try:
    from saslite.gui.app import app
except ModuleNotFoundError as exc:
    if exc.name != 'flask':
        raise
    app = None


@unittest.skipIf(app is None, 'GUI extra not installed')
class GuiSchemaDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.saved = app.config.copy()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'metadata').mkdir()
        (self.root / 'saslite-project.json').write_text(json.dumps({
            'version': 1, 'default_schema': 'weak', 'metadata_dir': 'metadata',
        }))
        app.config['SAS_FACTORY'] = SasInterpreter
        self.client = app.test_client()
        self.headers = {'X-SASLite-Token': app.config['SAS_API_TOKEN']}

    def tearDown(self):
        app.config.clear()
        app.config.update(self.saved)
        self.tmp.cleanup()

    def execute(self, *, physical=False, strict=False):
        if strict:
            metadata = self.root / 'metadata'
            (metadata / 'raw.csv').write_text(
                '#SASLITE_METADATA;1;RAW;2026-09-08T00:00:00\n'
                'DATASET;NAME;TYPE;LENGTH;POSITION;FORMAT;INFORMAT;LABEL\n'
                'FR;FREN;numeric;8;1;;;\n'
            )
        response = self.client.post('/api/profile', json={
            'profile_root': str(self.root),
        }, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.get_json())
        sas = app.config['SAS_SESSION']
        sas.session.storage.register('RAW', MemoryBackend())
        if physical:
            sas.create_dataset('FR', pd.DataFrame({'FREN': [1]}), libref='RAW')
        return self.client.post('/api/execute', json={'code': (
            'data temp1(keep=fren); set raw.fr; run; '
            'data temp2; set temp1; gren=qusen; run;'
        )}, headers=self.headers).get_json()

    def test_missing_weak_dataset_is_a_step_error(self):
        result = self.execute()
        libraries = self.client.get('/api/libraries').get_json()['libraries']
        policies = {lib['libref']: lib['schema_policy'] for lib in libraries}
        self.assertEqual(policies['WORK'], 'strict')
        self.assertEqual(policies['RAW'], 'weak')
        self.assertFalse(result['success'])
        self.assertIsNone(result['error'])
        self.assertEqual(result['steps'][0]['error'], 'Dataset RAW.FR does not exist')
        self.assertEqual(result['steps'][1]['error'], 'Dataset WORK.TEMP1 does not exist')

    def test_weak_variable_reports_original_source_through_work(self):
        result = self.execute(physical=True)
        self.assertTrue(result['success'], result)
        self.assertIn('RAW.FR.QUSEN', result['output'])
        self.assertFalse(result['steps'][-1]['warnings'])

    def test_metadata_enables_strict_without_physical_dataset(self):
        result = self.execute(strict=True)
        self.assertTrue(result['success'], result)
        self.assertIn('QUSEN', '\n'.join(result['steps'][-1]['warnings']).upper())
        self.assertNotIn('Expected source variables', result['output'])

    @unittest.skipUnless(shutil.which('node'), 'Node.js needed to exercise GUI renderer')
    def test_render_errors_once_and_preserve_fallbacks(self):
        result = self.execute()
        html = (Path(__file__).resolve().parents[1] /
                'src/saslite/gui/static/index.html').read_text()
        renderer = html.split('function renderOutput(result, runContext = null) {', 1)[1].split(
            '// ── Dataset browser', 1)[0]
        script = '''
const assert = require('node:assert/strict');
const output = {innerHTML: ''};
const badge = {};
const document = {getElementById: id => id === 'output-count' ? badge : output};
const escapeHtml = value => String(value).replaceAll('<', '&lt;');
function renderOutput(result, runContext = null) {''' + renderer + '\nconst result = ' + json.dumps(result) + ''';
renderOutput(result);
assert.equal(output.innerHTML.match(/Dataset RAW.FR does not exist/g).length, 1);
assert.equal(output.innerHTML.match(/Dataset WORK.TEMP1 does not exist/g).length, 1);
assert.ok(!output.innerHTML.includes('Unknown error'));
renderOutput({...result, output: ''});
assert.ok(output.innerHTML.includes('Dataset RAW.FR does not exist'));
assert.ok(!output.innerHTML.includes('Unknown error'));
renderOutput({success: false, error: '<failure>'});
assert.ok(output.innerHTML.includes('&lt;failure>'));
renderOutput({success: false});
assert.ok(output.innerHTML.includes('Unknown error'));
renderOutput({success: true, output: 'WARNING: Example\\n', steps: [{warnings: ['Example']}]});
assert.equal(output.innerHTML.replace(/<[^>]*>/g, '').match(/WARNING: Example/g).length, 1);
assert.ok(output.innerHTML.includes('<span class="warning-line">WARNING:</span>'));
assert.equal(badge.textContent, '(1)');
const context = {source: 'test.sas', document: 'source', origin: {line: 5, ch: 4}};
renderOutput({success: false, output: 'ERROR: test.sas:2:3: Missing data',
  steps: [{error: 'Missing data', warnings: ['Example']}]}, context);
assert.equal(badge.textContent, '(1)');
assert.equal(badge.className, 'output-count-error');
assert.equal(output.innerHTML.match(/Missing data/g).length, 1);
assert.ok(output.innerHTML.includes('<span class="error-line">ERROR:</span>'));
assert.ok(output.innerHTML.includes('focusDiagnostic(1, 2)'));
let sourcePath = 'test.sas';
let position, focused = false;
const editor = {getValue: () => 'source', setCursor: p => position = p,
  scrollIntoView: p => assert.deepEqual(p, position), focus: () => focused = true};
focusDiagnostic(1, 2);
assert.deepEqual(position, {line: 6, ch: 2});
assert.ok(focused);
focusDiagnostic(0, 2);
assert.deepEqual(position, {line: 5, ch: 6});
sourcePath = 'other.sas';
focused = false;
focusDiagnostic(1, 2);
assert.equal(focused, false);
assert.ok(!formatDiagnostic('ERROR: other.sas:2:1: Bad', context).includes('button'));
assert.ok(!formatDiagnostic('ERROR: Unknown error', context).includes('button'));
renderOutput({success: true});
assert.equal(badge.textContent, '');
'''
        checked = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(checked.returncode, 0, checked.stderr)
