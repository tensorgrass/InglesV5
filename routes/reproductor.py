"""
Rutas del reproductor de audios.
Listar pares y servir archivos MP3.
"""
import os
from flask import jsonify, request, render_template, abort, send_file
from mutagen.mp3 import MP3
from database import listar_temas_con_pares, obtener_tema_db
from audio_generator import limpiar_texto


def register(app):
    @app.route('/reproducir')
    def reproducir():
        """Página del reproductor de audios."""
        temas = listar_temas_con_pares(app)
        return render_template('reproducir.html', temas=temas)

    @app.route('/listar_audios', methods=['POST'])
    def listar_audios():
        """
        Escanea un tema en busca de pares ES/EN y devuelve la información.
        """
        data = request.get_json()
        tema_id = data.get('tema_id')

        if not tema_id:
            return jsonify({'success': False, 'error': 'Debes especificar un tema.'}), 400

        tema, pares = obtener_tema_db(app, tema_id)
        if not tema:
            return jsonify({'success': False, 'error': 'Tema no encontrado.'}), 400

        tema_dir = os.path.join(app.config['AUDIO_BASE'], limpiar_texto(tema['name']))

        if not os.path.isdir(tema_dir):
            return jsonify({'success': False, 'error': f'El directorio del tema no existe: {tema_dir}'}), 400

        # Construir lista de pares desde la BD
        lista_pares = []
        for p in pares:
            ruta_es = os.path.join(tema_dir, p['file_es'])
            ruta_en = os.path.join(tema_dir, p['file_en'])

            duracion_es = 0
            duracion_en = 0
            if os.path.isfile(ruta_es):
                try:
                    audio = MP3(ruta_es)
                    duracion_es = round(audio.info.length if audio.info else 0, 1)
                except Exception:
                    pass
            if os.path.isfile(ruta_en):
                try:
                    audio = MP3(ruta_en)
                    duracion_en = round(audio.info.length if audio.info else 0, 1)
                except Exception:
                    pass

            lista_pares.append({
                'clave': f"{tema['name']}_{p['line_number']:03d}",
                'es': {
                    'nombre': p['file_es'],
                    'ruta': ruta_es,
                    'duracion_segundos': duracion_es,
                    'texto': p['text_es']
                } if os.path.isfile(ruta_es) else None,
                'en': {
                    'nombre': p['file_en'],
                    'ruta': ruta_en,
                    'duracion_segundos': duracion_en,
                    'texto': p['text_en']
                } if os.path.isfile(ruta_en) else None,
                'pausa_ms': p['pause_ms']
            })

        return jsonify({
            'success': True,
            'tema': tema['name'],
            'tema_id': tema_id,
            'total_pares': len(lista_pares),
            'pares': lista_pares,
            'directorio': tema_dir
        })

    @app.route('/servir_audio')
    def servir_audio():
        """
        Sirve un archivo de audio individual para su reproducción en el navegador.
        """
        directorio = request.args.get('directorio', '').strip()
        archivo = request.args.get('archivo', '').strip()

        if not directorio or not archivo:
            abort(400, description='Faltan parámetros: directorio y archivo son requeridos.')

        directorio = os.path.normpath(directorio)
        archivo = os.path.basename(archivo)

        if not os.path.isdir(directorio):
            abort(400, description='El directorio no existe.')

        if not archivo.lower().endswith('.mp3'):
            abort(400, description='Solo se permiten archivos MP3.')

        ruta_completa = os.path.normpath(os.path.join(directorio, archivo))
        audio_base_norm = os.path.normpath(app.config['AUDIO_BASE'])
        if not ruta_completa.startswith(audio_base_norm):
            abort(403, description='Acceso denegado.')

        if not os.path.isfile(ruta_completa):
            abort(404, description='Archivo no encontrado.')

        return send_file(ruta_completa, mimetype='audio/mpeg', conditional=True)