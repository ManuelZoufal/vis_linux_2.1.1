from . import visualize_bp

from src.helpers import (allowed_file, get_marquee_text, login_required, log_change, get_background, save_background,
                         UPLOAD_FOLDER, MARQUEE_TEXT_FILE, ALLOWED_EXTENSIONS, BACKGROUND_NAME, BACKGROUND_OPACITY_RANGE)

from flask import render_template, request, redirect, url_for, flash, jsonify, session
import os

# /visualize
@visualize_bp.route('/')
def visualize():
    """Render the visualize page"""
    return render_template('visualize/visualization.html', marquee_text=get_marquee_text())

# /visualize/configure
@visualize_bp.route('/configure', methods=['GET', 'POST'])
@login_required(role=('Administrator', 'Benutzer'))
def configure_visualization():
    """Render the configure visualization page; a posted file becomes the background image of the display"""
    if request.method == 'POST':
        file = request.files.get('file')
        if not file or file.filename == '':
            flash('Es wurde keine Datei ausgewählt.', 'error')
        elif not allowed_file(file.filename):
            flash(f"Dateityp nicht erlaubt. Erlaubt sind: {', '.join(sorted(ALLOWED_EXTENSIONS))}.", 'error')
        else:
            # Stored under a fixed name, so an upload can never replace another file (e.g. the image of a group)
            filename = f"{BACKGROUND_NAME}.{file.filename.rsplit('.', 1)[1].lower()}"
            os.makedirs(UPLOAD_FOLDER, exist_ok=True)
            previous = get_background()
            if previous['file'] and previous['file'] != filename:
                _remove_background_file(previous['file'])
            file.save(os.path.join(UPLOAD_FOLDER, filename))
            save_background(filename, previous['opacity'])
            log_change(f"Background image of the display uploaded by user id {session.get('user_id')}: {filename}")
            flash('Das Hintergrundbild wurde gespeichert.', 'success')
        return redirect(url_for('visualize.configure_visualization'))
    return render_template('visualize/configure.html', marquee_text=get_marquee_text(), background=get_background(),
                           opacity_range=BACKGROUND_OPACITY_RANGE)


def _remove_background_file(name):
    try:
        os.remove(os.path.join(UPLOAD_FOLDER, name))
    except OSError:
        pass


# /visualize/background  (change the opacity or remove the image)
@visualize_bp.route('/background', methods=['POST'])
@login_required(role=('Administrator', 'Benutzer'))
def update_background():
    """Change the opacity of the background image or remove the image"""
    current = get_background()
    if request.form.get('action') == 'remove':
        if current['file']:
            _remove_background_file(current['file'])
            log_change(f"Background image of the display removed by user id {session.get('user_id')}")
        save_background(None, current['opacity'])
        flash('Das Hintergrundbild wurde entfernt.', 'success')
        return redirect(url_for('visualize.configure_visualization'))
    try:
        opacity = int(request.form.get('opacity', ''))
    except ValueError:
        opacity = None
    low, high = BACKGROUND_OPACITY_RANGE
    if opacity is None or not low <= opacity <= high:
        flash(f'Die Deckkraft muss eine ganze Zahl von {low} bis {high} sein.', 'error')
    else:
        save_background(current['file'], opacity)
        flash(f'Deckkraft des Hintergrundbilds: {opacity} %.', 'success')
    return redirect(url_for('visualize.configure_visualization'))


# /visualize/get_background
@visualize_bp.route('/get_background', methods=['GET'])
def get_background_route():
    """Background image for the display; open like the display itself"""
    background = get_background()
    return jsonify({'url': background['url'], 'opacity': background['opacity']})

# /visualize/update_marquee
@visualize_bp.route('/update_marquee', methods=['POST'])
@login_required(role=('Administrator', 'Benutzer'))
def update_marquee():
    """Update the marquee text"""
    marquee_text = request.form.get('marquee_text', '')
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    with open(MARQUEE_TEXT_FILE, 'w') as file:
        file.write(marquee_text)
    flash('Die Laufschrift wurde gespeichert.', 'success')
    return render_template('visualize/configure.html', marquee_text=get_marquee_text(), background=get_background(),
                           opacity_range=BACKGROUND_OPACITY_RANGE)

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
