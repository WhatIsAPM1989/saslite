"""Saving GUI programs writes only authorized SAS destinations."""
from unittest.mock import patch

from saslite.gui.app import app


def test_save_create_overwrite_and_authorization(tmp_path):
    client = app.test_client()
    headers = {'X-SASLite-Token': app.config['SAS_API_TOKEN']}
    path = tmp_path / 'Программа.sas'
    body = {'path': str(path), 'content': '/* Привет */\r\nrun;\r\n'}
    assert client.post('/api/save-file', json=body).status_code == 403
    assert not path.exists()
    result = client.post('/api/save-file', json=body, headers=headers)
    assert result.status_code == 200
    assert result.json['path'] == str(path)
    assert path.read_bytes() == body['content'].encode('utf-8')
    body['content'] = ''
    assert client.post('/api/save-file', json=body, headers=headers).status_code == 409
    assert path.read_bytes()
    body['overwrite'] = True
    assert client.post('/api/save-file', json=body, headers=headers).status_code == 200
    assert path.read_bytes() == b''


def test_invalid_save_and_failed_replace_preserve_file(tmp_path):
    client = app.test_client()
    headers = {'X-SASLite-Token': app.config['SAS_API_TOKEN']}
    for body in ({}, {'path': str(tmp_path / 'file.py'), 'content': 'x'},
                 {'path': str(tmp_path / 'file.sas'), 'content': None},
                 {'path': str(tmp_path / 'missing' / 'file.sas'), 'content': 'x'}):
        assert client.post('/api/save-file', json=body, headers=headers).status_code == 400
    path = tmp_path / 'original.sas'
    path.write_text('original')
    with patch('os.replace', side_effect=OSError('Write failed')):
        response = client.post('/api/save-file', json={
            'path': str(path), 'content': 'changed', 'overwrite': True}, headers=headers)
    assert response.status_code == 400
    assert path.read_text() == 'original'
    assert list(tmp_path.iterdir()) == [path]
