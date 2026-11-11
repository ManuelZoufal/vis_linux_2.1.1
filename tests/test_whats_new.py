"""Page "Was ist neu": change history from CHANGELOG.md"""
import re

import app as app_module
from conftest import ROOT, client_for
from src import changelog


def test_newest_entry_of_the_change_history_is_the_installed_version():
    """Every update raises APP_VERSION; this fails if the change history was forgotten."""
    entries = changelog.load(str(ROOT / 'CHANGELOG.md'))
    assert entries[0]['version'] == app_module.APP_VERSION
    assert all(entry['changes'] for entry in entries)
    versions = [tuple(int(part) for part in entry['version'].split('.')) for entry in entries]
    assert versions == sorted(versions, reverse=True) and len(set(versions)) == len(versions)
    assert all(entry['date'] is None or re.fullmatch(r'\d{4}-\d{2}-\d{2}', entry['date']) for entry in entries)


def test_page_shows_the_history_to_logged_in_users_only(admin, anonymous):
    response = anonymous.get('/whats_new')
    assert response.status_code == 302 and '/admin/login' in response.headers['Location']
    for client in (admin, client_for('Betrachter')):
        page = client.get('/whats_new').get_data(as_text=True)
        assert f"Version {app_module.APP_VERSION}" in page and 'Version 2.1.2' in page
        assert 'href="/whats_new"' in page


def test_version_is_a_link_only_when_logged_in(admin, anonymous):
    assert 'href="/whats_new"' in admin.get('/admin/').get_data(as_text=True)
    page = anonymous.get('/visualize/').get_data(as_text=True)
    assert 'href="/whats_new"' not in page and app_module.APP_VERSION in page


def test_file_is_parsed_as_text(tmp_path):
    path = tmp_path / 'CHANGELOG.md'
    path.write_text("# Titel\n\nEinleitung\n\n## 1.2.3 – 2026-01-02\n\n- Erste `code` Änderung\n- <b>Zweite</b>\n\n## 1.2.2\n\n- Alt\n", encoding='utf-8')
    entries = changelog.load(str(path))
    assert entries == [{'version': '1.2.3', 'date': '2026-01-02', 'changes': ['Erste `code` Änderung', '<b>Zweite</b>']},
                       {'version': '1.2.2', 'date': None, 'changes': ['Alt']}]
    assert changelog.split_code('Erste `code` Änderung') == [(False, 'Erste '), (True, 'code'), (False, ' Änderung')]
    assert changelog.load(str(tmp_path / 'fehlt.md')) == []


def test_html_in_the_history_is_escaped(admin, tmp_path, monkeypatch):
    path = tmp_path / 'CHANGELOG.md'
    path.write_text("## 9.9.9\n\n- <script>alert(1)</script>\n", encoding='utf-8')
    monkeypatch.setattr(changelog.os.path, 'join', lambda *parts: str(path) if parts[-1] == 'CHANGELOG.md' else '/'.join(parts))
    page = admin.get('/whats_new').get_data(as_text=True)
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in page and '<script>alert(1)' not in page
