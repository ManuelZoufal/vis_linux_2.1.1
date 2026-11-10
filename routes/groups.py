from . import group_bp

from src.database import get_connection

import json
from flask import jsonify

# /groups
@group_bp.route('/', methods=['GET'])
def get_groups():
    """Get all groups"""
    with open('config.json', 'r') as file:
        config = json.load(file)
    groups = config['groups']
    return jsonify(groups)

# /groups/<group_id>
@group_bp.route('/<group_id>', methods=['GET', 'POST'])
def group_occupancy(group_id):
    """Get group occupancy"""
    with open('config.json', 'r') as file:
        config = json.load(file)

    group_config = next((group for group in config['groups'] if str(group['group_id']) == group_id), None)
    if not group_config:
        return jsonify({'error': 'Group not found'}), 404

    max_occupancy = group_config['max_occupancy']
    welcome_text = group_config['welcome_text']

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT group_id, SUM(occupancy) as total_occupancy
        FROM sensor_data
        WHERE group_id = ?
        GROUP BY group_id
    ''', (group_id,))
    row = cursor.fetchone()
    conn.close()
    total_occupancy = row[1] if row else 0

    # Add virtual sensors' occupancy
    virtual_sensors = [s for s in config['sensors'] if s.get('type') == 'VIRTUAL' and str(s['group_id']) == group_id]
    for sensor in virtual_sensors:
        total_occupancy += int(sensor['occupancy'])  # Ensure occupancy is treated as an integer

    return jsonify({
        'group_id': group_id,
        'total_occupancy': total_occupancy,
        'max_occupancy': max_occupancy,
        'welcome_text': welcome_text
    })
