"""
Rutas de generación de audios.
Formulario, procesamiento asíncrono y polling de progreso.
"""
import os
from flask import jsonify, request, render_template, send_from_directory
from werkzeug.utils import secure_filename
from database import listar_temas_db, crear_tema
from audio_generator import limpiar_texto
from background import crear_task, lanzar_procesamiento, obtener_progreso_task, limpiar_task


def register(app):
    @app.route('/generar')
    def generar():
        """Formulario para generar audios."""
        temas = listar_temas_db(app)
        return render_template('generar.html', temas=temas)

    @app.route('/procesar', methods=['POST'])
    def procesar():
        """
        Endpoint que recibe el CSV y lanza la generación de audios en segundo plano.
        Devuelve un task_id para hacer polling del progreso.
        """
        if 'csv_file' not in request.files:
            return jsonify({'success': False, 'error': 'No se envió ningún archivo CSV.'}), 400

        file = request.files['csv_file']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'El nombre del archivo está vacío.'}), 400

        if not file.filename.lower().endswith('.csv'):
            return jsonify({'success': False, 'error': 'El archivo debe ser un CSV.'}), 400

        tema_nombre = request.form.get('tema', '').strip()
        if not tema_nombre:
            return jsonify({'success': False, 'error': 'Debes especificar el nombre del tema.'}), 400

        tema_descripcion = request.form.get('descripcion', '').strip()

        # Crear o recuperar el tema
        tema_id, msg = crear_tema(app, tema_nombre, tema_descripcion)

        # Crear directorio dentro de static/audio/<tema>
        tema_dir = os.path.join(app.config['AUDIO_BASE'], limpiar_texto(tema_nombre))
        os.makedirs(tema_dir, exist_ok=True)

        # Guardar el CSV subido a una ubicación temporal
        csv_filename = secure_filename(file.filename)
        csv_path = os.path.join(app.config['UPLOAD_FOLDER'], csv_filename)
        file.save(csv_path)

        # Crear tarea y lanzar procesamiento en segundo plano
        task_id = crear_task(tema_id, tema_nombre, tema_dir)
        lanzar_procesamiento(task_id, csv_path, tema_dir, tema_id,
                             tema_nombre, file.filename, app)

        # Responder inmediatamente con el task_id
        return jsonify({
            'success': True,
            'async': True,
            'task_id': task_id,
            'tema': tema_nombre,
            'tema_id': tema_id,
            'mensaje': 'Generación iniciada en segundo plano. Usa /progreso/<task_id> para seguir el avance.'
        })

    @app.route('/progreso/<task_id>')
    def obtener_progreso(task_id):
        """Endpoint para hacer polling del progreso de una tarea asíncrona."""
        task = obtener_progreso_task(task_id)

        if not task:
            return jsonify({'success': False, 'error': 'Tarea no encontrada o ya expiró.'}), 404

        response = {
            'success': True,
            'estado': task['estado'],
            'progreso': task['progreso'],
            'total': task['total'],
            'tema_id': task['tema_id'],
            'tema_nombre': task['tema_nombre']
        }

        if task['estado'] == 'completado':
            response['resultados'] = task['resultados']
            response['errores'] = task['errores']
            response['total_resultados'] = len(task['resultados'])
            response['total_errores'] = len(task['errores'])
            limpiar_task(task_id)

        if task['estado'] == 'error':
            response['error'] = task.get('error_global', 'Error desconocido durante la generación')
            limpiar_task(task_id)

        return jsonify(response)

    @app.route('/descargar/<path:filename>')
    def descargar_archivo(filename):
        """Descarga un archivo de audio individual."""
        output_dir = request.args.get('output_dir', '')
        if not output_dir or not os.path.isdir(output_dir):
            return jsonify({'success': False, 'error': 'Carpeta de salida no válida.'}), 400
        return send_from_directory(output_dir, filename)