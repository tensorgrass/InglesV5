"""
Rutas de gestión de temas (CRUD).
/api/temas - GET, POST, PUT, DELETE
"""
import os
import shutil
from flask import jsonify, request, render_template
from database import (listar_temas_db, obtener_tema_db, crear_tema,
                      actualizar_tema_db, eliminar_tema_db)


def register(app):
    @app.route('/api/temas')
    def listar_temas():
        """Devuelve la lista de temas con metadatos."""
        temas = listar_temas_db(app)
        return jsonify([{
            'id': t['id'],
            'name': t['name'],
            'description': t['description'],
            'total_pares': t['total_pares'],
            'created_at': t['created_at'],
            'updated_at': t['updated_at']
        } for t in temas])

    @app.route('/api/temas/<int:tema_id>')
    def obtener_tema(tema_id):
        """Devuelve un tema con sus pares de audio."""
        tema, pares = obtener_tema_db(app, tema_id)
        if not tema:
            return jsonify({'error': 'Tema no encontrado'}), 404

        return jsonify({
            'id': tema['id'],
            'name': tema['name'],
            'description': tema['description'],
            'created_at': tema['created_at'],
            'updated_at': tema['updated_at'],
            'pares': [{
                'id': p['id'],
                'line_number': p['line_number'],
                'text_es': p['text_es'],
                'text_en': p['text_en'],
                'file_es': p['file_es'],
                'file_en': p['file_en'],
                'pause_ms': p['pause_ms']
            } for p in pares]
        })

    @app.route('/api/temas', methods=['POST'])
    def crear_tema_api():
        """Crea un nuevo tema."""
        data = request.get_json()
        nombre = data.get('name', '').strip()
        if not nombre:
            return jsonify({'error': 'El nombre del tema es obligatorio'}), 400

        descripcion = data.get('description', '').strip()
        tema_id, msg = crear_tema(app, nombre, descripcion)
        return jsonify({'id': tema_id, 'name': nombre, 'description': descripcion, 'message': msg})

    @app.route('/api/temas/<int:tema_id>', methods=['PUT'])
    def actualizar_tema(tema_id):
        """Actualiza el nombre de un tema."""
        data = request.get_json()
        nombre = data.get('name', '').strip()
        if not nombre:
            return jsonify({'error': 'El nombre del tema es obligatorio'}), 400

        descripcion = data.get('description', '').strip()
        success, error = actualizar_tema_db(app, tema_id, nombre, descripcion)
        if not success:
            return jsonify({'error': error}), 400
        return jsonify({'success': True, 'name': nombre, 'description': descripcion})

    @app.route('/api/temas/<int:tema_id>', methods=['DELETE'])
    def eliminar_tema(tema_id):
        """Elimina un tema y sus archivos de audio."""
        tema = eliminar_tema_db(app, tema_id)
        if not tema:
            return jsonify({'error': 'Tema no encontrado'}), 404

        # Eliminar archivos de audio
        tema_dir = os.path.join(app.config['AUDIO_BASE'], tema['name'])
        if os.path.isdir(tema_dir):
            shutil.rmtree(tema_dir)

        return jsonify({'success': True})

    @app.route('/temas')
    def temas():
        """Página de gestión de temas."""
        return render_template('temas.html')