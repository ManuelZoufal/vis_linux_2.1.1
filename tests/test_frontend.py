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


def test_upload_never_replaces_an_existing_file():
    """A user with the role "Benutzer" could replace the display image of a group by using its file name."""
    import io
    uploads = WORK / 'static' / 'uploads'
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / 'group_1_img_0.png').write_bytes(b'Bild der Gruppe')
    client = client_for('Benutzer')
    for expected in ('group_1_img_0_1.png', 'group_1_img_0_2.png'):
        response = client.post('/visualize/configure', data={'file': (io.BytesIO(b'neu'), 'group_1_img_0.png')},
                               content_type='multipart/form-data')
        assert response.status_code == 302
        assert (uploads / expected).read_bytes() == b'neu'
    assert (uploads / 'group_1_img_0.png').read_bytes() == b'Bild der Gruppe'
    client.post('/visualize/configure', data={'file': (io.BytesIO(b'frei'), 'anderes.png')}, content_type='multipart/form-data')
    assert (uploads / 'anderes.png').read_bytes() == b'frei', "a free name is kept"
