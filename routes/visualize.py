from . import visualize_bp

from src.helpers import allowed_file, get_marquee_text, UPLOAD_FOLDER, MARQUEE_TEXT_FILE

from flask import render_template, request, redirect, url_for, flash, jsonify
from werkzeug.utils import secure_filename
import os

# /visualize
@visualize_bp.route('/')
def visualize():
    """Render the visualize page"""
    return render_template('visualize/visualization.html', marquee_text=get_marquee_text())

# /visualize/configure
@visualize_bp.route('/configure', methods=['GET', 'POST'])
def configure_visualization():
    """Render the configure visualization page"""
    if request.method == 'POST':
        if 'file' in request.files:
            file = request.files['file']
            if file.filename == '':
                flash('No selected file')
                return redirect(request.url)
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                if not os.path.exists(UPLOAD_FOLDER):
                    os.makedirs(UPLOAD_FOLDER)
                file.save(os.path.join(UPLOAD_FOLDER, filename))
                flash('File successfully uploaded')
                return redirect(url_for('visualize.display', filename=filename))
    return render_template('visualize/configure.html', marquee_text=get_marquee_text())

# /visualize/update_marquee
@visualize_bp.route('/update_marquee', methods=['POST'])
def update_marquee():
    """Update the marquee text"""
    marquee_text = request.form['marquee_text']
    with open(MARQUEE_TEXT_FILE, 'w') as file:
        file.write(marquee_text)
    return render_template('visualize/configure.html', marquee_text=get_marquee_text())

# /visualize/get_marquee_text
@visualize_bp.route('/get_marquee_text', methods=['GET'])
def get_marquee_text_route():
    """Get the marquee text"""
    return jsonify({'marquee_text': get_marquee_text()})

# /visualize/display
@visualize_bp.route('/display', endpoint='display')
def display():
    """Render the display page"""
    filename = request.args.get('filename', None)
    return render_template('visualize/display.html', filename=filename, marquee_text=get_marquee_text())
