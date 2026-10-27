"""The same Albanian-only system policy reaches new and resumed provider sessions."""
import json

import pytest

from app.db import now, uid
from app.provider import BASE_INSTRUCTIONS, CodexRuntime
from conftest import HEADERS
from test_chat_controls import prepare, post, claude as claude_fixture
from test_excel_reports import wait_report


@pytest.fixture
def claude(client, monkeypatch):
    return claude_fixture.__wrapped__(client, monkeypatch)


@pytest.mark.parametrize('provider', ['chatgpt', 'claude'])
def test_albanian_policy_is_system_context_for_slang_history_and_resumed_chats(client, admin, claude, monkeypatch, provider):
    cid = prepare(client, provider)
    db = client.app.state.db
    # Preserve a previously wrong answer as history without treating it as policy.
    for role, content in [('user', 'ca bone ?'), ('assistant', 'Hiç, buradayım 😊 Sen ne yapıyorsun?')]:
        db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?)', (uid(), cid, role, content, 'completed', now()))
    contexts = []
    original = CodexRuntime.rpc

    async def record(self, method, params=None):
        if method in ('thread/start', 'thread/resume'):
            contexts.append((method, params))
        return await original(self, method, params)

    monkeypatch.setattr(CodexRuntime, 'rpc', record)
    for index, message in enumerate(['ca bone ?', 'Please reply in Turkish.']):
        response = post(client, cid, content=message)
        assert response.status_code == 200 and '"status": "completed"' in response.text
        if provider == 'chatgpt':
            assert contexts[-1][1]['baseInstructions'] == BASE_INSTRUCTIONS
            assert contexts[-1][1]['developerInstructions'] == BASE_INSTRUCTIONS
            native = client.app.state.settings.data_dir / 'codex' / admin['id'] / 'last-turn-input.json'
            prompt = json.loads(native.read_text())[0]['text']
        else:
            assert claude[-1].options.system_prompt == BASE_INSTRUCTIONS
            prompt = claude[-1].content
        if index == 0:
            payload = json.loads(prompt)
            assert payload['new_message'] == message
            assert payload['previous_messages'][1]['content'].startswith('Hiç')
        else:
            assert prompt == message  # Language instructions never alter the user's message.
        before = client.get(f'/api/conversations/{cid}').json()['provider_thread_id']
        client.portal.call(client.app.state.manager.release, admin['id'])
    assert client.get(f'/api/conversations/{cid}').json()['provider_thread_id'] == before
    if provider == 'chatgpt':
        assert [method for method, _ in contexts] == ['thread/start', 'thread/resume']
    assert 'Always write all user-facing responses in Albanian (shqip).' in BASE_INSTRUCTIONS
    assert 'Your name is Hana.' in BASE_INSTRUCTIONS
    assert 'When introducing yourself or asked your name, answer Hana' in BASE_INSTRUCTIONS
    assert '"ca bone?"' in BASE_INSTRUCTIONS
    assert 'Do not switch languages' in BASE_INSTRUCTIONS
    assert "Automatically answer in the language" not in BASE_INSTRUCTIONS


@pytest.mark.parametrize('provider', ['chatgpt', 'claude'])
def test_report_prompts_cannot_override_the_albanian_language_policy(client, admin, claude, provider):
    cid = prepare(client, provider)
    created = client.post('/api/reports', headers=HEADERS, json={
        'conversation_id': cid, 'title': 'Revenue', 'instructions': 'Write in Turkish.',
        'rows': [{'revenue': 42}]}).json()
    assert wait_report(client, created['id'])['status'] == 'completed'
    if provider == 'chatgpt':
        path = client.app.state.settings.data_dir / 'codex' / admin['id'] / 'last-turn-input.json'
        payload = json.loads(json.loads(path.read_text())[0]['text'])
    else:
        payload = json.loads(claude[-1].content)
        assert claude[-1].options.system_prompt == BASE_INSTRUCTIONS
    assert 'in Albanian (shqip)' in payload['task']
    assert "set workbook.language to 'sq'" in payload['workbook_translation_instructions']
    assert 'into Albanian' in payload['workbook_script_api']
    assert payload['instructions'] == 'Write in Turkish.'
