import asyncio
import csv
import json
import os
import re
import sqlite3
import sys
import tempfile
from datetime import datetime
from werkzeug.utils import secure_filename

import glob
from flask import Flask, render_template, request, jsonify, send_from_directory, send_file, abort
from mutagen.mp3 import MP3

try:
    import edge_tts
except ImportError:
    print("Por favor, instala las librerías requeridas ejecutando:")
    print("pip install edge-tts flask")
    sys.exit(1)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max upload
app.config['UPLOAD_FOLDER'] = tempfile.gettempdir()
app.config['AUDIO_BASE'] = os.path.join(app.root_path, 'static', 'audio')
app.config['DATABASE'] = os.path.join(app.root_path, 'database.db')

PREFIJO = "audio"

# ──────────────────────────────────────────────
#  Base de datos SQLite
# ──────────────────────────────────────────────

def get_db():
    """Obtiene una conexión a la base de datos."""
    conn = sqlite3.connect(app.config['DATABASE'])
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    """Inicializa la base de datos creando las tablas si no existen."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.executescript('''
        CREATE TABLE IF NOT EXISTS themes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS audio_pairs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            theme_id INTEGER NOT NULL,
            line_number INTEGER NOT NULL,
            text_es TEXT NOT NULL,
            text_en TEXT NOT NULL,
            file_es TEXT NOT NULL,
            file_en TEXT NOT NULL,
            pause_ms INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (theme_id) REFERENCES themes(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS csv_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            theme_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (theme_id) REFERENCES themes(id) ON DELETE CASCADE
        );
    ''')
    conn.commit()
    conn.close()

# Inicializar BD al arrancar
init_db()

def crear_tema(nombre, descripcion=''):
    """Crea un nuevo tema y devuelve su ID."""
    conn = get_db()
    try:
        cursor = conn.execute("INSERT INTO themes (name, description) VALUES (?, ?)", (nombre, descripcion))
        conn.commit()
        tema_id = cursor.lastrowid
        return tema_id, None
    except sqlite3.IntegrityError:
        # El tema ya existe, devolver su ID
        cursor = conn.execute("SELECT id FROM themes WHERE name = ?", (nombre,))
        row = cursor.fetchone()
        if row and descripcion:
            conn.execute("UPDATE themes SET description = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (descripcion, row['id']))
            conn.commit()
        return row['id'], "Tema existente actualizado" if row else None
    finally:
        conn.close()

def guardar_pares_en_bd(tema_id, resultados):
    """Guarda los resultados de la generación en la base de datos."""
    conn = get_db()
    try:
        for r in resultados:
            conn.execute(
                "INSERT INTO audio_pairs (theme_id, line_number, text_es, text_en, file_es, file_en, pause_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (tema_id, r['linea'], r['texto_es'], r['texto_en'], r['archivo_es'], r['archivo_en'], r['pausa_ms'])
            )
        conn.commit()
    finally:
        conn.close()

# ──────────────────────────────────────────────
#  Funciones del núcleo
# ──────────────────────────────────────────────

def limpiar_texto(texto):
    """Sanitiza texto para usarlo como nombre de archivo."""
    texto_limpio = texto.lower()
    texto_limpio = texto_limpio.replace('á', 'a').replace('é', 'e').replace('í', 'i').replace('ó', 'o').replace('ú', 'u').replace('ñ', 'n')
    texto_limpio = re.sub(r'[^a-z0-9]', '_', texto_limpio)
    texto_limpio = re.sub(r'_+', '_', texto_limpio)
    return texto_limpio.strip('_')


def calcular_pausa_estimada(texto_en):
    """
    Calcula un tiempo de pausa estimado basado en la longitud del texto en inglés.
    ~150ms por palabra como tiempo de reacción.
    """
    num_palabras = len(texto_en.split())
    return max(800, num_palabras * 150 + 300)


async def generar_audios_desde_csv(csv_path, output_dir, progreso_callback=None):
    """
    Procesa el CSV y genera los audios (ES y EN por separado).
    """
    resultados = []
    errores = []

    with open(csv_path, mode='r', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader, None)

        for index, row in enumerate(reader):
            if len(row) < 2:
                continue

            es_text = row[0].strip()
            en_text = row[1].strip()

            if not es_text or not en_text:
                continue

            line_num = index + 1

            if progreso_callback:
                progreso_callback({
                    'linea': line_num,
                    'es_text': es_text,
                    'en_text': en_text,
                    'estado': 'procesando'
                })

            texto_formateado = limpiar_texto(es_text)
            base_name = f"{PREFIJO}_{line_num:03d}_{texto_formateado}"
            archivo_es = f"{base_name}_es.mp3"
            archivo_en = f"{base_name}_en.mp3"
            ruta_es = os.path.join(output_dir, archivo_es)
            ruta_en = os.path.join(output_dir, archivo_en)

            try:
                communicate_es = edge_tts.Communicate(es_text, "es-ES-AlvaroNeural")
                communicate_en = edge_tts.Communicate(en_text, "en-US-GuyNeural")

                await communicate_es.save(ruta_es)
                await communicate_en.save(ruta_en)

                pausa_ms = calcular_pausa_estimada(en_text)

                resultados.append({
                    'linea': line_num,
                    'archivo_es': archivo_es,
                    'archivo_en': archivo_en,
                    'pausa_ms': pausa_ms,
                    'texto_es': es_text,
                    'texto_en': en_text
                })

                if progreso_callback:
                    progreso_callback({
                        'linea': line_num,
                        'es_text': es_text,
                        'en_text': en_text,
                        'estado': 'completado',
                        'archivo_es': archivo_es,
                        'archivo_en': archivo_en
                    })

            except Exception as e:
                errores.append({
                    'linea': line_num,
                    'texto': es_text,
                    'error': str(e)
                })
                for ruta in [ruta_es, ruta_en]:
                    if os.path.exists(ruta):
                        os.remove(ruta)

                if progreso_callback:
                    progreso_callback({
                        'linea': line_num,
                        'es_text': es_text,
                        'en_text': en_text,
                        'estado': 'error',
                        'error': str(e)
                    })

    return resultados, errores


# ──────────────────────────────────────────────
#  Rutas de la aplicación Flask
# ──────────────────────────────────────────────

@app.route('/')
def index():
    """Página principal con el menú."""
    return render_template('index.html')


# ── Gestión de temas ──

@app.route('/api/temas')
def listar_temas():
    """Devuelve la lista de temas con metadatos."""
    conn = get_db()
    temas = conn.execute("""
        SELECT t.*, COUNT(ap.id) as total_pares
        FROM themes t
        LEFT JOIN audio_pairs ap ON ap.theme_id = t.id
        GROUP BY t.id
        ORDER BY t.updated_at DESC
    """).fetchall()
    conn.close()
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
    conn = get_db()
    tema = conn.execute("SELECT * FROM themes WHERE id = ?", (tema_id,)).fetchone()
    if not tema:
        conn.close()
        return jsonify({'error': 'Tema no encontrado'}), 404
    
    pares = conn.execute("""
        SELECT * FROM audio_pairs
        WHERE theme_id = ?
        ORDER BY line_number ASC
    """, (tema_id,)).fetchall()
    conn.close()
    
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
    tema_id, msg = crear_tema(nombre, descripcion)
    return jsonify({'id': tema_id, 'name': nombre, 'description': descripcion, 'message': msg})


@app.route('/api/temas/<int:tema_id>', methods=['PUT'])
def actualizar_tema(tema_id):
    """Actualiza el nombre de un tema."""
    data = request.get_json()
    nombre = data.get('name', '').strip()
    if not nombre:
        return jsonify({'error': 'El nombre del tema es obligatorio'}), 400
    
    conn = get_db()
    try:
        descripcion = data.get('description', '').strip()
        conn.execute("UPDATE themes SET name = ?, description = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (nombre, descripcion, tema_id))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Ya existe un tema con ese nombre'}), 400
    finally:
        conn.close()
    return jsonify({'success': True, 'name': nombre, 'description': descripcion})


@app.route('/api/temas/<int:tema_id>', methods=['DELETE'])
def eliminar_tema(tema_id):
    """Elimina un tema y sus archivos de audio."""
    conn = get_db()
    tema = conn.execute("SELECT * FROM themes WHERE id = ?", (tema_id,)).fetchone()
    if not tema:
        conn.close()
        return jsonify({'error': 'Tema no encontrado'}), 404
    
    # Eliminar archivos de audio
    tema_dir = os.path.join(app.config['AUDIO_BASE'], tema['name'])
    if os.path.isdir(tema_dir):
        import shutil
        shutil.rmtree(tema_dir)
    
    # Los pares se borran en cascada por la FK
    conn.execute("DELETE FROM themes WHERE id = ?", (tema_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ── Generación de audios ──

@app.route('/generar')
def generar():
    """Formulario para generar audios."""
    conn = get_db()
    temas = conn.execute("SELECT id, name FROM themes ORDER BY name").fetchall()
    conn.close()
    return render_template('generar.html', temas=temas)


@app.route('/procesar', methods=['POST'])
def procesar():
    """
    Endpoint que recibe el CSV, nombre del tema y genera los audios.
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
    tema_id, msg = crear_tema(tema_nombre, tema_descripcion)

    # Crear directorio dentro de static/audio/<tema>
    tema_dir = os.path.join(app.config['AUDIO_BASE'], limpiar_texto(tema_nombre))
    os.makedirs(tema_dir, exist_ok=True)

    # Guardar el CSV subido a una ubicación temporal
    csv_filename = secure_filename(file.filename)
    csv_path = os.path.join(app.config['UPLOAD_FOLDER'], csv_filename)
    file.save(csv_path)

    # Procesar los audios
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        resultados, errores = loop.run_until_complete(
            generar_audios_desde_csv(csv_path, tema_dir)
        )
        loop.close()
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error durante la generación: {e}'}), 500
    finally:
        if os.path.exists(csv_path):
            os.remove(csv_path)

    # Guardar en BD
    if resultados:
        guardar_pares_en_bd(tema_id, resultados)
        
        # Guardar registro del CSV
        conn = get_db()
        conn.execute("INSERT INTO csv_files (theme_id, filename) VALUES (?, ?)",
                    (tema_id, file.filename))
        conn.execute("UPDATE themes SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (tema_id,))
        conn.commit()
        conn.close()

    # Actualizar la fecha del tema
    conn = get_db()
    conn.execute("UPDATE themes SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (tema_id,))
    conn.commit()
    conn.close()

    response = {
        'success': True,
        'total': len(resultados),
        'errores': len(errores),
        'resultados': resultados,
        'tema': tema_nombre,
        'tema_id': tema_id,
        'carpeta': tema_dir
    }

    if errores:
        response['detalles_errores'] = errores

    return jsonify(response)


@app.route('/descargar/<path:filename>')
def descargar_archivo(filename):
    """Descarga un archivo de audio individual."""
    output_dir = request.args.get('output_dir', '')
    if not output_dir or not os.path.isdir(output_dir):
        return jsonify({'success': False, 'error': 'Carpeta de salida no válida.'}), 400
    return send_from_directory(output_dir, filename)


# ── Reproductor de audios ──

@app.route('/reproducir')
def reproducir():
    """Página del reproductor de audios."""
    conn = get_db()
    temas = conn.execute("""
        SELECT t.*, COUNT(ap.id) as total_pares
        FROM themes t
        LEFT JOIN audio_pairs ap ON ap.theme_id = t.id
        GROUP BY t.id
        HAVING total_pares > 0
        ORDER BY t.updated_at DESC
    """).fetchall()
    conn.close()
    return render_template('reproducir.html', temas=temas)


@app.route('/listar_audios', methods=['POST'])
def listar_audios():
    """
    Escanea un directorio en busca de archivos MP3 con el patrón de la aplicación,
    los agrupa en pares y devuelve la información ordenada.
    """
    data = request.get_json()
    tema_id = data.get('tema_id')
    
    if not tema_id:
        return jsonify({'success': False, 'error': 'Debes especificar un tema.'}), 400

    conn = get_db()
    tema = conn.execute("SELECT * FROM themes WHERE id = ?", (tema_id,)).fetchone()
    if not tema:
        conn.close()
        return jsonify({'success': False, 'error': f'Tema no encontrado.'}), 400
    
    pares = conn.execute("""
        SELECT * FROM audio_pairs
        WHERE theme_id = ?
        ORDER BY line_number ASC
    """, (tema_id,)).fetchall()
    conn.close()

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


def calcular_pausa_por_duracion(duracion_segundos):
    """Calcula la pausa en milisegundos basada en la duración del audio en inglés."""
    return int(duracion_segundos * 700)


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
    # Permitir que el archivo esté dentro de static/audio
    audio_base_norm = os.path.normpath(app.config['AUDIO_BASE'])
    if not ruta_completa.startswith(audio_base_norm):
        abort(403, description='Acceso denegado.')

    if not os.path.isfile(ruta_completa):
        abort(404, description='Archivo no encontrado.')

    return send_file(ruta_completa, mimetype='audio/mpeg', conditional=True)


# ── Página de edición de temas ──

@app.route('/temas')
def temas():
    """Página de gestión de temas."""
    return render_template('temas.html')


# ── Exponer archivos estáticos de audio ──

@app.route('/static/audio/<path:filename>')
def audio_static(filename):
    """Sirve archivos de audio estáticos."""
    return send_from_directory(app.config['AUDIO_BASE'], filename)


if __name__ == '__main__':
    # Asegurar que existe el directorio base de audio
    os.makedirs(app.config['AUDIO_BASE'], exist_ok=True)
    app.run(debug=True, host='0.0.0.0', port=5000)