"""Browser GUI preserves native selection paths and cancellation semantics."""
import subprocess
import unittest
from unittest.mock import patch

from saslite.gui.file_dialog import choose_macos_file

try:
    from saslite.gui.app import app
except ModuleNotFoundError as exc:
    if exc.name != 'flask':
        raise
    app = None


class MacFileDialogTests(unittest.TestCase):
    def setUp(self):
        patcher = patch('saslite.gui.file_dialog.threading.Thread')
        patcher.start()
        self.addCleanup(patcher.stop)

    @patch('saslite.gui.file_dialog.subprocess.run')
    def test_selected_path_is_returned_unchanged(self, run):
        path = '/Users/example/Проект with spaces/program.sas'
        run.return_value = subprocess.CompletedProcess([], 0, path + '\n', '')
        self.assertEqual(choose_macos_file('open'), {'success': True, 'path': path})
        args = run.call_args.args[0]
        self.assertEqual(args[0], '/usr/bin/osascript')
        self.assertEqual(args[-1], 'open')
        self.assertNotIn('shell', run.call_args.kwargs)

    @patch('saslite.gui.file_dialog.subprocess.run')
    def test_cancel_is_distinct_from_unavailable(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, '\n', '')
        self.assertEqual(choose_macos_file('open'), {'success': False, 'cancelled': True})
        run.return_value = subprocess.CompletedProcess([], 1, '', 'Permission denied')
        with self.assertRaisesRegex(RuntimeError, 'Permission denied'):
            choose_macos_file('open')


@unittest.skipIf(app is None, 'GUI extra not installed')
class FileDialogApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.headers = {'X-SASLite-Token': app.config['SAS_API_TOKEN']}

    @patch.dict('sys.modules', {'webview': None})
    @patch('saslite.gui.app.sys.platform', 'darwin')
    @patch('saslite.gui.file_dialog.choose_macos_file')
    def test_browser_uses_system_dialog_without_pywebview(self, choose):
        for payload in ({'success': True, 'path': '/tmp/program.sas'},
                        {'success': False, 'cancelled': True}):
            choose.return_value = payload
            response = self.client.post('/api/file-dialog', json={'mode': 'open'}, headers=self.headers)
            self.assertEqual(response.get_json(), payload)
        choose.assert_called_with('open')

    @patch('saslite.gui.file_dialog.choose_macos_file')
    def test_invalid_and_unauthorized_requests_never_open_dialog(self, choose):
        self.assertEqual(self.client.post('/api/file-dialog', json={'mode':'open'}).status_code, 403)
        self.assertEqual(self.client.post('/api/file-dialog', json={'mode':'bad'}, headers=self.headers).status_code, 400)
        choose.assert_not_called()


class WarmPickerTests(unittest.TestCase):
    @patch('saslite.gui.file_dialog.threading.Thread')
    @patch('saslite.gui.file_dialog._choose_macos_file_fallback')
    def test_selection_and_cancel_close_helper_before_return(self, fallback, thread):
        from unittest.mock import Mock
        for response in ({'success': True, 'path': '/tmp/demo.sas'},
                         {'success': False, 'cancelled': True}):
            picker = Mock()
            picker.request.return_value = response
            with patch('saslite.gui.file_dialog._picker', picker):
                self.assertEqual(choose_macos_file('open'), response)
                picker.close.assert_called_once()
                from saslite.gui import file_dialog
                self.assertIsNone(file_dialog._picker)
            thread.return_value.start.assert_called()
        fallback.assert_not_called()

    @patch('saslite.gui.file_dialog.threading.Thread')
    @patch('saslite.gui.file_dialog._choose_macos_file_fallback')
    @patch('saslite.gui.file_dialog._picker')
    def test_failed_helper_closes_before_fallback(self, picker, fallback, thread):
        picker.request.side_effect = BrokenPipeError()
        def fallback_result(mode):
            picker.close.assert_called()
            return {'success': False, 'cancelled': True}
        fallback.side_effect = fallback_result
        self.assertTrue(choose_macos_file('open')['cancelled'])
        fallback.assert_called_once_with('open')

    @patch('saslite.gui.file_dialog._picker', None)
    @patch('saslite.gui.file_dialog._NativePicker')
    def test_warmup_starts_only_one_helper(self, native):
        from saslite.gui import file_dialog
        file_dialog.warm_macos_picker()
        file_dialog.warm_macos_picker()
        native.assert_called_once()
