"""Native file selection for the browser GUI on macOS."""
from __future__ import annotations

import atexit
import json
import queue
import subprocess
import threading


_MAC_FILE_DIALOG = '''on run argv
    activate
    try
        if item 1 of argv is "open" then
            set picked to choose file with prompt "Open SAS program" of type {"sas"}
        else
            set picked to choose file with prompt "Import data" of type {"sas7bdat", "xpt", "csv", "xlsx", "xls"}
        end if
        return POSIX path of picked
    on error number -128
        return ""
    end try
end run'''


def _choose_macos_file_fallback(mode: str) -> dict:
    """Return an absolute path or cancellation; no user text becomes script code."""
    result = subprocess.run(
        ['/usr/bin/osascript', '-e', _MAC_FILE_DIALOG, mode],
        capture_output=True, text=True, timeout=300, check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'Could not open the system file dialog')
    path = result.stdout.rstrip('\n')
    return {'success': True, 'path': path} if path else {'success': False, 'cancelled': True}


# Preload Cocoa before the click. Each helper handles one selection and exits
# so no closing NSOpenPanel animation can freeze while waiting on stdin.
_NATIVE_PICKER = r"""
ObjC.import('Cocoa');
const input = $.NSFileHandle.fileHandleWithStandardInput;
const output = $.NSFileHandle.fileHandleWithStandardOutput;
const app = $.NSApplication.sharedApplication;
app.setActivationPolicy($.NSApplicationActivationPolicyAccessory);
function send(value) {
    const line = $(JSON.stringify(value) + '\n');
    output.writeData(line.dataUsingEncoding($.NSUTF8StringEncoding));
}
function readLine() {
    let line = '';
    while (true) {
        const data = input.readDataOfLength(1);
        if (data.length === 0) return null;
        const part = $.NSString.alloc.initWithDataEncoding(data, $.NSUTF8StringEncoding).js;
        if (part === '\n') return line;
        line += part;
    }
}
// Preload the panel as well as Cocoa before the first click.
const panel = $.NSOpenPanel.openPanel;
panel.canChooseDirectories = false;
panel.canChooseFiles = true;
panel.allowsMultipleSelection = false;
send({ready:true});
while (true) {
    const line = readLine();
    if (line === null) break;
    const mode = JSON.parse(line);
    if (mode === 'ping') { send({ready:true}); continue; }
    panel.allowedFileTypes = mode === 'open' ? ['sas'] : ['sas7bdat','xpt','csv','xlsx','xls'];
    panel.title = mode === 'open' ? 'Open SAS program' : 'Import data';
    const previousApp = $.NSWorkspace.sharedWorkspace.frontmostApplication;
    app.activateIgnoringOtherApps(true);
    let response;
    if (panel.runModal === $.NSModalResponseOK) {
        response = {success:true, path:panel.URL.path.js};
    } else {
        response = {success:false, cancelled:true};
    }
    // Finish the UI lifecycle before blocking on stdin again. Otherwise this
    // accessory process can retain application/key-window focus after selection.
    panel.orderOut(null);
    app.hide(null);
    if (previousApp && !previousApp.isTerminated) {
        previousApp.activateWithOptions($.NSApplicationActivateIgnoringOtherApps);
    }
    send(response);
    break; // Never block this UI process on stdin after displaying a panel.
}
"""


class _NativePicker:
    def __init__(self):
        self.lock = threading.Lock()
        self.messages = queue.Queue()
        self.process = subprocess.Popen(
            ['/usr/bin/osascript', '-l', 'JavaScript', '-e', _NATIVE_PICKER],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1,
        )
        threading.Thread(target=self._read, daemon=True).start()
        try:
            if self.messages.get(timeout=20) != {'ready': True}:
                raise RuntimeError('Native picker did not start')
        except Exception:
            self.close()
            raise

    def _read(self):
        try:
            for line in self.process.stdout:
                self.messages.put(json.loads(line))
        except (ValueError, OSError):
            pass
        finally:
            self.messages.put(None)

    def request(self, mode):
        with self.lock:
            if self.process.poll() is not None:
                raise RuntimeError('Native picker stopped')
            self.process.stdin.write(json.dumps(mode) + '\n')
            self.process.stdin.flush()
            response = self.messages.get(timeout=300)
            if not isinstance(response, dict):
                raise RuntimeError('Native picker disconnected')
            return response

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        for stream in (self.process.stdin, self.process.stdout):
            stream.close()


_picker = None
_picker_lock = threading.Lock()


def warm_macos_picker():
    """Start once at GUI startup, off the request path."""
    global _picker
    with _picker_lock:
        if _picker is not None:
            return
        try:
            _picker = _NativePicker()
        except Exception:
            # The original system dialog remains available if Cocoa cannot start.
            return


def close_macos_picker():
    global _picker
    with _picker_lock:
        if _picker is not None:
            _picker.close()
            _picker = None


atexit.register(close_macos_picker)


def choose_macos_file(mode: str) -> dict:
    global _picker
    if mode not in ('open', 'import'):
        raise ValueError('Unknown file dialog mode')
    with _picker_lock:
        picker, _picker = _picker, None
    if picker is not None:
        try:
            return picker.request(mode)
        except Exception:
            # Close a failed panel before showing the fallback system dialog.
            picker.close()
            return _choose_macos_file_fallback(mode)
        finally:
            picker.close()
            threading.Thread(target=warm_macos_picker, daemon=True).start()
    try:
        return _choose_macos_file_fallback(mode)
    finally:
        threading.Thread(target=warm_macos_picker, daemon=True).start()
