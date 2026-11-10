from . import root_bp

from flask import render_template

from src.helpers import login_required


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

@root_bp.route('/schedules', endpoint='schedules')
@login_required(role='Administrator')
def schedules():
    return render_template('schedules.html')
