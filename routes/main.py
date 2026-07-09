"""
Rutas principales: página de inicio y archivos estáticos de audio.
"""
from flask import render_template, send_from_directory


def register(app):
    @app.route('/')
    def index():
        """Página principal con el menú."""
        return render_template('index.html')

    @app.route('/static/audio/<path:filename>')
    def audio_static(filename):
        """Sirve archivos de audio estáticos."""
        return send_from_directory(app.config['AUDIO_BASE'], filename)