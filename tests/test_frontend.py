"""Checks on templates and scripts that need no browser"""
import re

import pytest

from conftest import ROOT, WORK, client_for

SCRIPTS = sorted((ROOT / 'static' / 'js').glob('*.js'))
TEMPLATES = sorted((ROOT / 'templates').rglob('*.html'))


@pytest.mark.parametrize('script', SCRIPTS, ids=lambda path: path.name)
def test_scripts_do_not_build_html_from_data(script):
    """Names and texts from the server were once inserted with innerHTML, which let a group name run script."""
    text = script.read_text(encoding='utf-8')
    assert not re.search(r"innerHTML\s*=\s*[^'\";]*[`$]", text), "innerHTML with a template or variable"
    assert not re.search(r'insertAdjacentHTML|document\.write|outerHTML\s*=', text)
    assert not re.search(r"on(click|change)=\"[^\"]*\$\{", text), "inline handler built from data"


@pytest.mark.parametrize('script', SCRIPTS, ids=lambda path: path.name)
def test_scripts_contain_no_template_expressions(script):
    """Static files are not rendered: a Jinja expression in display.js once broke the marquee refresh."""
    assert '{{' not in script.read_text(encoding='utf-8')


@pytest.mark.parametrize('template', TEMPLATES, ids=lambda path: str(path.relative_to(ROOT / 'templates')))
def test_templates_load_nothing_from_other_servers(template):
    """The display must work without internet access."""
    text = template.read_text(encoding='utf-8')
    assert not re.search(r'(src|href)="https?://', text)
    assert '|safe' not in text.replace(' ', '')


def test_vendored_libraries_are_present_and_referenced():
    assert (ROOT / 'static' / 'vendor' / 'chart.umd.min.js').stat().st_size > 100000
    assert 'vendor/chart.umd.min.js' in (ROOT / 'templates' / 'visualize' / 'display.html').read_text(encoding='utf-8')


def test_no_secrets_or_runtime_files_are_tracked():
    import subprocess
    tracked = subprocess.run(['git', 'ls-files'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    forbidden = [name for name in tracked
                 if name.endswith(('.pem', '.key', '.pyc', '.db')) or name in ('.env', 'change_log.txt') or name.startswith('logs/')]
    assert forbidden == []


def test_group_name_with_html_is_delivered_as_data_and_escaped_in_templates(admin):
    payload = '<img src=x onerror=alert(1)>'
    assert admin.post('/api/groups/1/edit', json={'name': payload, 'welcome_text': payload}).status_code == 200
    assert admin.get('/api/get_data').get_json()['groups'][0]['name'] == payload
    admin.post('/visualize/update_marquee', data={'marquee_text': payload})
    html = admin.get('/visualize/display?group_id=1').get_data(as_text=True)
    assert payload not in html and '&lt;img src=x onerror=alert(1)&gt;' in html


def test_every_script_a_template_loads_exists():
    """A page once loaded a script that failed at once because the form it looked for did not exist."""
    for template in TEMPLATES:
        for name in re.findall(r"filename='(js/[^']+)'", template.read_text(encoding='utf-8')):
            assert (ROOT / 'static' / name).exists(), f"{template.name} loads {name}"


def test_marquee_text_can_be_changed_and_is_read_by_the_display(admin, anonymous):
    assert admin.post('/visualize/update_marquee', data={'marquee_text': 'Heute geschlossen'}).status_code == 200
    assert anonymous.get('/visualize/get_marquee_text').get_json() == {'marquee_text': 'Heute geschlossen'}


def test_env_template_names_every_variable_the_code_reads():
    """The template once listed variables nobody read and missed most of the ones that are read."""
    read = set()
    for path in [ROOT / 'app.py', *sorted((ROOT / 'src').glob('*.py')), *sorted((ROOT / 'routes').glob('*.py'))]:
        read.update(re.findall(r"os\.environ(?:\.get)?[\[(]\s*['\"]([A-Z_]+)['\"]", path.read_text(encoding='utf-8')))
    template = (ROOT / '.env.example').read_text(encoding='utf-8')
    documented = set(re.findall(r'^#?\s*([A-Z][A-Z0-9_<>]*)=', template, flags=re.MULTILINE))
    assert read - documented == set(), "read by the code but missing in .env.example"
    sensor_keys = {name for name in documented if name.startswith('SENSOR_')}
    assert sensor_keys == {'SENSOR_IEE_PASSWORD', 'SENSOR_HANWHA_USERNAME', 'SENSOR_HANWHA_PASSWORD',
                           'SENSOR_<ID>_USERNAME', 'SENSOR_<ID>_PASSWORD'}
    assert documented - read - sensor_keys == set(), "in .env.example but not read by the code"


def test_visualization_page_offers_the_tile_view_without_login(anonymous):
    html = anonymous.get('/visualize/').get_data(as_text=True)
    assert 'id="group-tiles"' in html and 'js/visualize.js' in html
    script = (ROOT / 'static' / 'js' / 'visualize.js').read_text(encoding='utf-8')
    # The preview is the real display page of the group, and the group id is escaped in its address
    assert '/visualize/display?group_id=${encodeURIComponent(groupId)}' in script
    assert "frame.loading = 'lazy'" in script, "previews outside the window are not loaded"


def test_display_page_can_be_shown_inside_the_tile_view(anonymous):
    """The preview embeds the display page; a header that forbids framing would leave the tiles empty."""
    response = anonymous.get('/visualize/display?group_id=1')
    assert response.status_code == 200
    assert 'X-Frame-Options' not in response.headers
    assert 'frame-ancestors' not in response.headers.get('Content-Security-Policy', '')


def upload(client, name, content=b'bild'):
    import io
    return client.post('/visualize/configure', data={'file': (io.BytesIO(content), name)}, content_type='multipart/form-data')


def background(client):
    return client.get('/visualize/get_background').get_json()


def test_uploaded_image_becomes_the_background_of_the_display(anonymous):
    uploads = WORK / 'static' / 'uploads'
    assert background(anonymous) == {'url': None, 'opacity': 20}
    client = client_for('Benutzer')
    assert upload(client, 'Mein Foto.PNG', b'eins').status_code == 302
    assert (uploads / 'background.png').read_bytes() == b'eins'
    shown = background(anonymous)
    assert shown['url'].startswith('/static/uploads/background.png?v=') and shown['opacity'] == 20
    page = client.get('/visualize/configure').get_data(as_text=True)
    assert 'Das Hintergrundbild wurde gespeichert.' in page and shown['url'] in page
    # A new image replaces the old one, also with another file type; the opacity is kept
    assert client.post('/visualize/background', data={'action': 'save', 'opacity': '35'}).status_code == 302
    upload(client, 'neu.jpg', b'zwei')
    assert not (uploads / 'background.png').exists() and (uploads / 'background.jpg').read_bytes() == b'zwei'
    assert background(anonymous)['url'].startswith('/static/uploads/background.jpg?v=') and background(anonymous)['opacity'] == 35
    # Removing deletes the file
    assert client.post('/visualize/background', data={'action': 'remove'}).status_code == 302
    assert not (uploads / 'background.jpg').exists() and background(anonymous) == {'url': None, 'opacity': 35}
    assert 'id="background-image"' in anonymous.get('/visualize/display?group_id=1').get_data(as_text=True)


def test_upload_cannot_replace_other_files_and_only_takes_images(anonymous):
    """A user with the role "Benutzer" could replace the display image of a group by using its file name."""
    uploads = WORK / 'static' / 'uploads'
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / 'group_1_img_0.png').write_bytes(b'Bild der Gruppe')
    client = client_for('Benutzer')
    upload(client, 'group_1_img_0.png', b'neu')
    upload(client, '../../config.png', b'neu')
    assert (uploads / 'group_1_img_0.png').read_bytes() == b'Bild der Gruppe'
    assert sorted(path.name for path in uploads.iterdir()) == ['background.json', 'background.png', 'group_1_img_0.png']
    response = upload(client, 'skript.html', b'<script>')
    assert 'Dateityp nicht erlaubt' in client.get('/visualize/configure').get_data(as_text=True) or response.status_code == 302
    assert not (uploads / 'background.html').exists() and background(anonymous)['url'].startswith('/static/uploads/background.png')


def test_opacity_must_be_within_the_range(anonymous):
    client = client_for('Benutzer')
    upload(client, 'bild.gif')
    for value in ('4', '101', 'viel', ''):
        client.post('/visualize/background', data={'action': 'save', 'opacity': value})
        assert background(anonymous)['opacity'] == 20, value
    client.post('/visualize/background', data={'action': 'save', 'opacity': '100'})
    assert background(anonymous)['opacity'] == 100


def test_background_can_only_be_changed_after_login(anonymous):
    assert upload(anonymous, 'bild.png').status_code == 302
    assert anonymous.post('/visualize/background', data={'action': 'remove'}).status_code == 302
    assert not (WORK / 'static' / 'uploads' / 'background.png').exists()
    assert client_for('Betrachter').post('/visualize/background', data={'action': 'save', 'opacity': '50'}).status_code in (302, 403)
    assert background(anonymous) == {'url': None, 'opacity': 20}


def test_damaged_settings_file_gives_no_background(anonymous):
    uploads = WORK / 'static' / 'uploads'
    uploads.mkdir(parents=True, exist_ok=True)
    for content in ('kein json', '{"file": "../../config.json", "opacity": 50}', '{"file": "group_1_img_0.png", "opacity": "x"}', '[1]'):
        (uploads / 'background.json').write_text(content)
        assert background(anonymous)['url'] is None, content


def test_ticker_repeats_instead_of_using_the_marquee_element(admin, anonymous):
    """The <marquee> element shows a text once and starts again only after it has left the screen."""
    admin.post('/visualize/update_marquee', data={'marquee_text': 'Heute <b>Pasta</b> & mehr'})
    page = anonymous.get('/visualize/display?group_id=1').get_data(as_text=True)
    assert '<marquee' not in page
    assert 'class="marquee" data-initial="Heute &lt;b&gt;Pasta&lt;/b&gt; &amp; mehr"' in page
    assert 'js/marquee.js' in page and 'css/marquee.css' in page
    script = (ROOT / 'static/js/marquee.js').read_text(encoding='utf-8')
    assert 'cloneNode(true)' in script and 'textContent = text' in script
    assert "const MARQUEE_SEPARATOR = '***';" in script, "<text> *** <text> *** <text>"


def test_configuration_page_shows_previews_and_confirms_saving(admin):
    page = admin.get('/visualize/configure').get_data(as_text=True)
    for expected in ('id="display-preview"', 'id="marquee-preview"', 'Kein Hintergrundbild hinterlegt', 'js/configure.js'):
        assert expected in page
    assert 'id="opacity"' not in page, "no opacity control without an image"
    upload(admin, 'bild.png')
    page = admin.get('/visualize/configure').get_data(as_text=True)
    assert 'type="range" id="opacity"' in page and 'id="preview-image"' in page and 'Bild entfernen' in page
    saved = admin.post('/visualize/update_marquee', data={'marquee_text': 'Neu'}).get_data(as_text=True)
    assert 'Die Laufschrift wurde gespeichert.' in saved and 'data-initial="Neu"' in saved


def test_license_file_names_every_package_with_its_pinned_version():
    """THIRD-PARTY-LICENSES.txt must be renewed when a version in requirements.txt changes."""
    text = (ROOT / 'THIRD-PARTY-LICENSES.txt').read_text(encoding='utf-8')
    pinned = [line.strip().split('==') for line in (ROOT / 'requirements.txt').read_text(encoding='utf-8').splitlines() if '==' in line]
    assert len(pinned) == 14
    for name, version in pinned:
        assert f"\n{name} {version}\nLizenz: " in text, name
    assert '\nChart.js 4.6.1\n' in text and '\nchartjs-plugin-datalabels 2.2.0\n' in text
    assert '--- NOTICE ---' in text, "requests is under the Apache licence, its NOTICE file belongs to it"
