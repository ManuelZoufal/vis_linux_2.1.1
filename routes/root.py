from . import root_bp

import os

from flask import render_template, current_app

from src.helpers import login_required
from src import changelog


@root_bp.route('/', endpoint='index')
def index():
    return render_template('general_overview.html')

@root_bp.route('/sensor_settings', methods=['GET', 'POST'], endpoint='sensor_settings')
@login_required(role='Administrator')
def sensor_settings():
    return render_template('sensor_settings.html')

@root_bp.route('/general_overview', endpoint='general_overview')
def general_overview():
    return render_template('general_overview.html')

@root_bp.route('/group_settings', endpoint='group_settings')
@login_required(role='Administrator')
def group_settings():
    return render_template('group_settings.html')


@root_bp.route('/logs', endpoint='logs')
@login_required()
def logs():
    return render_template('logs.html')

@root_bp.route('/settings', endpoint='settings')
@login_required(role='Administrator')
def settings():
    """Certificate, verbose server log and links to the credential pages"""
    return render_template('settings.html')


@root_bp.route('/schedules', endpoint='schedules')
@login_required(role='Administrator')
def schedules():
    return render_template('schedules.html')


@root_bp.route('/whats_new', endpoint='whats_new')
@login_required()
def whats_new():
    """Change history, opened by a click on the version number"""
    entries = changelog.load(os.path.join(current_app.root_path, 'CHANGELOG.md'))
    return render_template('whats_new.html', entries=entries, split_code=changelog.split_code)
