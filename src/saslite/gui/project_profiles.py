"""Discover project profile paths without executing editor commands or Python."""
from __future__ import annotations

import json
import re
import shlex
from pathlib import Path


def _editor_settings(path: Path) -> dict:
    if not path.is_file():
        return {}
    # VS Code settings are JSON with comments and optional trailing commas.
    text = re.sub(r'("(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/)',
                  lambda m: m[0] if m[0].startswith('"') else '', path.read_text())
    text = re.sub(r'("(?:\\.|[^"\\])*"|,\s*[}\]])',
                  lambda m: m[0] if m[0].startswith('"') else m[0][1:], text)
    result = json.loads(text)
    return result if isinstance(result, dict) else {}


def _runner_options(settings: dict, root: Path) -> dict:
    commands = [settings.get('code-runner.executorMapByFileExtension', {}).get('.sas'),
                settings.get('code-runner.executorMap', {}).get('sas'),
                settings.get('code-runner.customCommand')]
    for command in commands:
        if not isinstance(command, str):
            continue
        # Never evaluate shell syntax. Only extract explicit configuration flags.
        command = command.replace('${workspaceFolder}', str(root)).replace('$workspaceRoot', str(root))
        tokens = shlex.split(command)
        options = {}
        for index, token in enumerate(tokens):
            flag, sep, inline = token.partition('=')
            if flag not in ('--profile-file', '--profile-root', '--profile', '--project-file'):
                continue
            value = inline if sep else (tokens[index + 1] if index + 1 < len(tokens) else '')
            if not value or '$' in value or '`' in value:
                raise ValueError(f'Cannot resolve {flag} in project Run settings')
            key = flag[2:].replace('-', '_')
            if key != 'profile':
                path = Path(value).expanduser()
                value = str((path if path.is_absolute() else root / path).resolve())
            options[key] = value
        if options.get('profile_file') or options.get('profile'):
            return options
    return {}


def expected_profile(program: str, active: dict) -> dict:
    path = Path(program).expanduser().resolve()
    if not path.is_file() or path.suffix.lower() != '.sas':
        raise ValueError('Choose an existing .sas program')
    root = path.parent
    for parent in path.parents:
        if any((parent / marker).exists() for marker in
               ('saslite-project.json', '.vscode/settings.json', '.git', '_local/config/localsetup.sas')):
            root = parent
            break
    settings = _editor_settings(root / '.vscode/settings.json')
    options = _runner_options(settings, root)
    origin = 'Project Run settings' if options else 'Conventional project profile'
    explicit = bool(options)
    if not options:
        candidates = [root / '_local/config/saslite_profile.py', root / 'saslite_profile.py']
        options = {'profile_file': str(next((p for p in candidates if p.is_file()), candidates[0]))}
    options.setdefault('profile_root', str(root))
    same_root = active.get('profile_root') == options['profile_root']
    same_profile = (active.get('profile_file') == options.get('profile_file') and
                    active.get('profile') == options.get('profile'))
    # A manually connected profile for this project is valid if Run specifies none.
    matches = bool(active.get('name')) and same_root and (same_profile or not explicit)
    if matches and not explicit:
        options = {key: active.get(key) for key in ('profile', 'profile_file', 'profile_root', 'project_file')}
    exists = bool(options.get('profile')) or bool(options.get('profile_file') and Path(options['profile_file']).is_file())
    return dict(path=str(path), project_root=str(root), settings=options, origin=origin,
                exists=exists, matches=matches,
                template=profile_template(root) if not exists else None)


def profile_template(root: Path) -> str:
    return f'''"""Local profile. Add project-specific macro/path rules here."""
from pathlib import Path
from saslite.profiles.base import CompatibilityProfile


class ProjectProfile(CompatibilityProfile):
    name = {root.name!r}

    def __init__(self, project_root=None):
        self.root = Path(project_root or {str(root)!r}).resolve()

    def prepare_source(self, source, *, source_name):
        setup = self.root / "_local/config/localsetup.sas"
        if setup.is_file():
            escaped = str(setup).replace('"', '""')
            return f\'%include "{{escaped}}";\\n{{source}}\'
        return source


def create_profile(*, project_root=None):
    return ProjectProfile(project_root=project_root)
'''
