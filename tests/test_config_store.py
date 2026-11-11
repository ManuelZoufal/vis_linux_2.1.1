"""config.json: locked and atomic writes"""
import os
import stat
import threading

from conftest import WORK, client_for, read_config

from src import config_store


def test_save_keeps_the_permissions_and_leaves_no_temporary_file():
    os.chmod(WORK / 'config.json', 0o640)
    config = config_store.load_config()
    config['groups'][0]['name'] = 'Geändert'
    config_store.save_config(config)
    assert stat.S_IMODE(os.stat(WORK / 'config.json').st_mode) == 0o640
    assert read_config()['groups'][0]['name'] == 'Geändert'
    assert [name for name in os.listdir(WORK) if name.startswith('.config.')] == []


def test_parallel_changes_do_not_lose_each_other():
    """Without the lock two requests read the same state and the later write discarded the earlier one."""
    admin = client_for('Administrator')
    cookie = admin.get_cookie('session').value
    statuses = []

    def add(index):
        from conftest import new_client
        client = new_client()
        client.set_cookie('session', cookie, domain='localhost')
        statuses.append(client.put('/api/sensors/virtual/add', json={'name': f'V{index}', 'group_id': '1', 'occupancy': index}).status_code)
    threads = [threading.Thread(target=add, args=(index,)) for index in range(25)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    virtual = [s for s in read_config()['sensors'] if s['type'] == 'VIRTUAL']
    assert statuses == [200] * 25
    assert len(virtual) == 25 and len({s['sensor_id'] for s in virtual}) == 25
