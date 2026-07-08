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
        reader = csv.reader(f, delimiter=';')
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


# ── Exportación de temas ──

@app.route('/exportar')
def exportar():
    """Página para exportar un tema a un directorio."""
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
    return render_template('exportar.html', temas=temas)


@app.route('/api/exportar', methods=['POST'])
def api_exportar():
    """
    Exporta un tema: copia los audios al directorio destino y genera un HTML
    que funciona offline con el mismo comportamiento que el reproductor.
    """
    data = request.get_json()
    tema_id = data.get('tema_id')
    destino = data.get('destino', '').strip()

    if not tema_id:
        return jsonify({'success': False, 'error': 'Debes especificar un tema.'}), 400
    if not destino:
        return jsonify({'success': False, 'error': 'Debes especificar el directorio de destino.'}), 400

    conn = get_db()
    tema = conn.execute("SELECT * FROM themes WHERE id = ?", (tema_id,)).fetchone()
    if not tema:
        conn.close()
        return jsonify({'success': False, 'error': 'Tema no encontrado.'}), 404

    pares = conn.execute("""
        SELECT * FROM audio_pairs
        WHERE theme_id = ?
        ORDER BY line_number ASC
    """, (tema_id,)).fetchall()
    conn.close()

    if not pares:
        return jsonify({'success': False, 'error': 'El tema no tiene pares de audio.'}), 400

    tema_dir = os.path.join(app.config['AUDIO_BASE'], limpiar_texto(tema['name']))
    if not os.path.isdir(tema_dir):
        return jsonify({'success': False, 'error': f'El directorio del tema no existe: {tema_dir}'}), 400

    import shutil

    # Crear directorio destino
    os.makedirs(destino, exist_ok=True)

    pares_exportados = []
    errores = []

    for p in pares:
        archivo_es = p['file_es']
        archivo_en = p['file_en']
        ruta_origen_es = os.path.join(tema_dir, archivo_es)
        ruta_origen_en = os.path.join(tema_dir, archivo_en)
        ruta_dest_es = os.path.join(destino, archivo_es)
        ruta_dest_en = os.path.join(destino, archivo_en)

        try:
            if os.path.isfile(ruta_origen_es):
                shutil.copy2(ruta_origen_es, ruta_dest_es)
            if os.path.isfile(ruta_origen_en):
                shutil.copy2(ruta_origen_en, ruta_dest_en)

            pares_exportados.append({
                'linea': p['line_number'],
                'texto_es': p['text_es'],
                'texto_en': p['text_en'],
                'archivo_es': archivo_es,
                'archivo_en': archivo_en,
                'pausa_ms': p['pause_ms']
            })
        except Exception as e:
            errores.append({
                'linea': p['line_number'],
                'texto': p['text_es'],
                'error': str(e)
            })

    # Generar el HTML offline
    html_offline = generar_html_offline(tema['name'], pares_exportados, destino)
    html_path = os.path.join(destino, f"{limpiar_texto(tema['name'])}_player.html")
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_offline)

    response = {
        'success': True,
        'tema': tema['name'],
        'destino': destino,
        'total_exportados': len(pares_exportados),
        'errores': len(errores),
        'archivo_html': os.path.basename(html_path)
    }

    if errores:
        response['detalles_errores'] = errores

    return jsonify(response)


def generar_html_offline(tema_nombre, pares, directorio_audios):
    """
    Genera un HTML autónomo que funciona offline.
    Los audios se sirven desde rutas relativas (mismo directorio).
    """
    import json as json_mod

    pares_json = json_mod.dumps(pares, ensure_ascii=False, indent=2)

    html = f'''<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{tema_nombre} - Reproductor Offline</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacFontSystem, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            color: #333;
            line-height: 1.6;
        }}

        .container {{
            max-width: 800px;
            margin: 0 auto;
            padding: 2rem 1rem;
        }}

        header {{
            text-align: center;
            margin-bottom: 2rem;
            color: white;
        }}

        header h1 {{
            font-size: 2.5rem;
            margin-bottom: 0.5rem;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.2);
        }}

        .subtitle {{
            font-size: 1.1rem;
            opacity: 0.9;
        }}

        .card {{
            background: white;
            border-radius: 12px;
            padding: 1.5rem;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            margin-bottom: 1.5rem;
        }}

        .card h2 {{
            margin-bottom: 1rem;
            color: #667eea;
        }}

        .file-list {{
            max-height: 300px;
            overflow-y: auto;
            background: #f9f9f9;
            border-radius: 8px;
            padding: 0.5rem;
            margin-bottom: 1rem;
        }}

        .file-item {{
            padding: 0.3rem 0.5rem;
            border-bottom: 1px solid #eee;
            font-size: 0.9rem;
            cursor: pointer;
            transition: background 0.15s;
        }}

        .file-item:last-child {{
            border-bottom: none;
        }}

        .file-item:hover {{
            background: #f5f5ff;
        }}

        .file-item.active {{
            background: #e8e8ff;
            border-left: 4px solid #667eea;
            font-weight: 600;
        }}

        .pair-header {{
            font-weight: 600;
            color: #667eea;
            padding: 0.5rem 0;
            font-size: 0.9rem;
            border-bottom: 1px solid #e0e0e0;
            margin-bottom: 0.3rem;
        }}

        .file-pair {{
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 0.3rem;
        }}

        .pair-num {{
            font-weight: 600;
            color: #999;
            min-width: 1.5rem;
        }}

        .pair-es {{
            color: #333;
        }}

        .pair-arrow {{
            color: #aaa;
            font-size: 0.9rem;
        }}

        .pair-en {{
            color: #333;
        }}

        .pair-pause {{
            color: #667eea;
            font-size: 0.8rem;
            margin-left: auto;
        }}

        .player-controls {{
            margin-top: 1rem;
            text-align: center;
        }}

        .btn-play {{
            padding: 0.7rem 2rem;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 1.1rem;
            font-weight: 600;
            cursor: pointer;
            transition: opacity 0.2s, transform 0.1s;
        }}

        .btn-play:hover {{
            opacity: 0.9;
        }}

        .btn-play:active {{
            transform: scale(0.98);
        }}

        .btn-play:disabled {{
            opacity: 0.5;
            cursor: not-allowed;
        }}

        .progress-bar-container {{
            width: 100%;
            height: 20px;
            background: #e0e0e0;
            border-radius: 10px;
            overflow: hidden;
            margin-bottom: 0.5rem;
        }}

        .progress-bar {{
            height: 100%;
            width: 0%;
            background: linear-gradient(90deg, #667eea, #764ba2);
            border-radius: 10px;
            transition: width 0.3s ease;
        }}

        .time-display {{
            text-align: center;
            font-size: 0.95rem;
            color: #666;
            margin-bottom: 0.5rem;
            font-family: monospace;
        }}

        .transport-controls {{
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 1rem;
            margin: 1rem 0;
        }}

        .btn-transport {{
            width: 50px;
            height: 50px;
            border: none;
            border-radius: 50%;
            background: #f0f0f0;
            font-size: 1.3rem;
            cursor: pointer;
            transition: background 0.2s, transform 0.1s;
            display: inline-flex;
            align-items: center;
            justify-content: center;
        }}

        .btn-transport:hover {{
            background: #e0e0e0;
        }}

        .btn-transport:active {{
            transform: scale(0.92);
        }}

        .btn-large {{
            width: 60px;
            height: 60px;
            font-size: 1.6rem;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }}

        .btn-large:hover {{
            opacity: 0.9;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }}

        .phase-indicator {{
            text-align: center;
            margin-bottom: 1rem;
            padding: 0.5rem;
            background: #f9f9f9;
            border-radius: 8px;
            min-height: 40px;
            display: flex;
            align-items: center;
            justify-content: center;
        }}

        .phase-phase {{
            font-size: 1.1rem;
            font-weight: 600;
            color: #555;
            animation: fadeIn 0.3s ease;
        }}

        .phase-done {{
            color: #28a745;
        }}

        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(-5px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}

        @keyframes fadeOut {{
            from {{ opacity: 1; }}
            to {{ opacity: 0; }}
        }}

        .playlist-info {{
            text-align: center;
            font-size: 0.9rem;
            color: #888;
            margin-top: 0.5rem;
        }}

        .hidden {{
            display: none;
        }}

        .info-card {{
            background: #f0f4ff;
            border-left: 4px solid #667eea;
        }}

        .empty-msg {{
            text-align: center;
            color: #999;
            padding: 1rem;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🎧 {tema_nombre}</h1>
            <p class="subtitle">Reproductor offline - Español → Inglés con pausa inteligente</p>
        </header>

        <div id="fileListArea" class="card">
            <h2>Lista de reproducción</h2>
            <div id="fileListContainer" class="file-list"></div>
            <div class="player-controls">
                <button id="btnPlayAll" class="btn-play">▶️ Reproducir todo</button>
            </div>
        </div>

        <div id="playerArea" class="card hidden">
            <h2 id="nowPlaying">Reproduciendo: —</h2>
            <div id="phaseIndicator" class="phase-indicator">
                <span id="phaseEs" class="phase-phase">🇪🇸 Escuchando español...</span>
                <span id="phasePause" class="phase-phase hidden">⏸️ Pausa de <span id="pauseCountdown">0</span>ms...</span>
                <span id="phaseEn" class="phase-phase hidden">🇬🇧 Repitiendo en inglés...</span>
                <span id="phaseDone" class="phase-phase phase-done hidden">✅ ¡Completado!</span>
            </div>
            <div class="progress-bar-container">
                <div class="progress-bar" id="playbackProgress"></div>
            </div>
            <div class="time-display">
                <span id="currentTime">00:00</span> / <span id="totalTime">00:00</span>
            </div>
            <div class="transport-controls">
                <button id="btnPrev" class="btn-transport" title="Anterior">⏮️</button>
                <button id="btnPlayPause" class="btn-transport btn-large" title="Reproducir/Pausar">▶️</button>
                <button id="btnStop" class="btn-transport" title="Parar">⏹️</button>
                <button id="btnNext" class="btn-transport" title="Siguiente">⏭️</button>
            </div>
            <p id="playlistInfo" class="playlist-info">Par 0 de 0</p>
        </div>
    </div>

    <script>
        // Datos de los pares exportados
        const pares = {pares_json};

        // ── Estado del reproductor ──
        let currentIndex = -1;
        let isPlaying = false;
        let isPaused = false;
        let phase = 'stopped';   // 'stopped', 'es', 'pause', 'en', 'done'
        let audioElement = null;
        let pauseTimeout = null;
        let audioErrorHandler = null;

        // ── Elementos DOM ──
        const fileListContainer = document.getElementById('fileListContainer');
        const playerArea = document.getElementById('playerArea');
        const btnPlayAll = document.getElementById('btnPlayAll');
        const nowPlaying = document.getElementById('nowPlaying');
        const phaseEs = document.getElementById('phaseEs');
        const phasePause = document.getElementById('phasePause');
        const phaseEn = document.getElementById('phaseEn');
        const phaseDone = document.getElementById('phaseDone');
        const pauseCountdown = document.getElementById('pauseCountdown');
        const playbackProgress = document.getElementById('playbackProgress');
        const currentTimeSpan = document.getElementById('currentTime');
        const totalTimeSpan = document.getElementById('totalTime');
        const btnPrev = document.getElementById('btnPrev');
        const btnPlayPause = document.getElementById('btnPlayPause');
        const btnStop = document.getElementById('btnStop');
        const btnNext = document.getElementById('btnNext');
        const playlistInfo = document.getElementById('playlistInfo');

        // ── Utilidades ──
        function formatTime(seconds) {{
            if (isNaN(seconds) || seconds < 0) return '00:00';
            const m = Math.floor(seconds / 60);
            const s = Math.floor(seconds % 60);
            return `${{String(m).padStart(2, '0')}}:${{String(s).padStart(2, '0')}}`;
        }}

        function escapeHtml(text) {{
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }}

        function ocultarTodasLasFases() {{
            phaseEs.classList.add('hidden');
            phasePause.classList.add('hidden');
            phaseEn.classList.add('hidden');
            phaseDone.classList.add('hidden');
        }}

        function mostrarFase(fase) {{
            ocultarTodasLasFases();
            if (fase === 'es') phaseEs.classList.remove('hidden');
            else if (fase === 'pause') phasePause.classList.remove('hidden');
            else if (fase === 'en') phaseEn.classList.remove('hidden');
            else if (fase === 'done') phaseDone.classList.remove('hidden');
            phase = fase;
        }}

        function obtenerParActual() {{
            if (currentIndex >= 0 && currentIndex < pares.length) {{
                return pares[currentIndex];
            }}
            return null;
        }}

        // ── Mostrar lista ──
        function mostrarLista() {{
            let html = '';
            if (pares.length > 0) {{
                html += `<div class="pair-header">Pares Español ↔ Inglés:</div>`;
                pares.forEach((p, i) => {{
                    html += `<div class="file-item file-pair" data-index="${{i}}">
                        <span class="pair-num">${{i + 1}}.</span>
                        <span class="pair-es">🇪🇸 ${{escapeHtml(p.texto_es)}} <small>(${{p.archivo_es}})</small></span>
                        <span class="pair-arrow">→</span>
                        <span class="pair-en">🇬🇧 ${{escapeHtml(p.texto_en)}} <small>(${{p.archivo_en}})</small></span>
                        <span class="pair-pause">⏸️ ${{p.pausa_ms}}ms</span>
                    </div>`;
                }});
            }}

            if (!html) {{
                html = '<p class="empty-msg">No hay pares para reproducir.</p>';
                btnPlayAll.disabled = true;
            }}

            fileListContainer.innerHTML = html;

            fileListContainer.querySelectorAll('.file-pair').forEach(el => {{
                el.addEventListener('click', function() {{
                    const idx = parseInt(this.dataset.index);
                    reproducirParDesde(idx);
                }});
            }});
        }}

        // ── Reproducir par desde índice ──
        function reproducirParDesde(idx) {{
            if (idx < 0 || idx >= pares.length) return;
            currentIndex = idx;
            limpiarAudio();
            if (pauseTimeout) {{ clearInterval(pauseTimeout); pauseTimeout = null; }}
            playerArea.classList.remove('hidden');
            reproducirFaseEs();
        }}

        // ── Reproducir fase ES ──
        function reproducirFaseEs() {{
            const par = obtenerParActual();
            if (!par || !par.archivo_es) {{
                if (par && par.archivo_en) {{ reproducirFaseEn(); return; }}
                avanzarAlSiguiente();
                return;
            }}

            mostrarFase('es');
            const url = par.archivo_es;
            prepararAudio(url, function() {{
                mostrarFase('pause');
                iniciarPausa();
            }});
            nowPlaying.textContent = `🇪🇸 ${{par.texto_es}}`;
            playlistInfo.textContent = `Par ${{currentIndex + 1}} de ${{pares.length}}`;
            actualizarResaltado();
        }}

        // ── Reproducir fase EN ──
        function reproducirFaseEn() {{
            const par = obtenerParActual();
            if (!par || !par.archivo_en) {{
                avanzarAlSiguiente();
                return;
            }}

            mostrarFase('en');
            const url = par.archivo_en;
            prepararAudio(url, function() {{
                mostrarFase('done');
                setTimeout(function() {{ avanzarAlSiguiente(); }}, 800);
            }});
            nowPlaying.textContent = `🇬🇧 ${{par.texto_en}}`;
        }}

        // ── Preparar y reproducir un audio ──
        function prepararAudio(url, onEndedCallback) {{
            limpiarAudio();

            audioElement = new Audio(url);
            audioElement.preload = 'auto';

            audioElement.addEventListener('loadedmetadata', function() {{
                totalTimeSpan.textContent = formatTime(audioElement.duration);
                playbackProgress.style.width = '0%';
                currentTimeSpan.textContent = '00:00';
            }});

            audioElement.addEventListener('timeupdate', function() {{
                if (audioElement.duration) {{
                    const pct = (audioElement.currentTime / audioElement.duration) * 100;
                    playbackProgress.style.width = pct + '%';
                    currentTimeSpan.textContent = formatTime(audioElement.currentTime);
                }}
            }});

            audioElement.addEventListener('ended', function() {{
                if (onEndedCallback) onEndedCallback();
            }});

            audioErrorHandler = function() {{
                console.error('Error al reproducir audio');
                if (onEndedCallback) onEndedCallback();
            }};
            audioElement.addEventListener('error', audioErrorHandler);

            audioElement.play().then(() => {{
                isPlaying = true;
                isPaused = false;
                btnPlayPause.textContent = '⏸️';
            }}).catch(function(err) {{
                console.error('No se pudo iniciar la reproducción:', err);
                if (onEndedCallback) onEndedCallback();
            }});
        }}

        // ── Iniciar pausa calculada ──
        function iniciarPausa() {{
            const par = obtenerParActual();
            if (!par) return;

            const pausaMs = par.pausa_ms;
            pauseCountdown.textContent = pausaMs;

            const startTime = Date.now();
            pauseTimeout = setInterval(function() {{
                const elapsed = Date.now() - startTime;
                const remaining = Math.max(0, pausaMs - elapsed);
                pauseCountdown.textContent = remaining;
                const pct = Math.min((elapsed / pausaMs) * 100, 100);
                playbackProgress.style.width = pct + '%';
                currentTimeSpan.textContent = formatTime(elapsed / 1000);

                if (remaining <= 0) {{
                    clearInterval(pauseTimeout);
                    pauseTimeout = null;
                    reproducirFaseEn();
                }}
            }}, 50);
            totalTimeSpan.textContent = formatTime(pausaMs / 1000);
        }}

        // ── Avanzar al siguiente par ──
        function avanzarAlSiguiente() {{
            if (currentIndex < pares.length - 1) {{
                const nextIdx = currentIndex + 1;
                if (nextIdx < pares.length) {{
                    reproducirParDesde(nextIdx);
                }}
            }} else {{
                isPlaying = false;
                isPaused = false;
                btnPlayPause.textContent = '▶️';
                nowPlaying.textContent = '🎉 Reproducción finalizada';
                mostrarFase('done');
                document.getElementById('phaseDone').textContent = '✅ ¡Lista completa!';
                playbackProgress.style.width = '100%';
                currentTimeSpan.textContent = '00:00';
                totalTimeSpan.textContent = '00:00';
                actualizarResaltado();
            }}
        }}

        // ── Limpiar solo el audio ──
        function limpiarAudio() {{
            if (audioElement) {{
                if (audioErrorHandler) {{
                    audioElement.removeEventListener('error', audioErrorHandler);
                    audioErrorHandler = null;
                }}
                audioElement.pause();
                audioElement.src = '';
                audioElement.load();
                audioElement = null;
            }}
        }}

        // ── Detener reproducción ──
        function detenerReproduccion() {{
            limpiarAudio();
            isPlaying = false;
            isPaused = false;
            btnPlayPause.textContent = '▶️';
            playbackProgress.style.width = '0%';
            currentTimeSpan.textContent = '00:00';
            totalTimeSpan.textContent = '00:00';
        }}

        // ── Actualizar resaltado ──
        function actualizarResaltado() {{
            fileListContainer.querySelectorAll('.file-item').forEach(el => {{
                el.classList.remove('active');
                if (parseInt(el.dataset.index) === currentIndex) {{
                    el.classList.add('active');
                    el.scrollIntoView({{ block: 'nearest', behavior: 'smooth' }});
                }}
            }});
        }}

        // ── Eventos de botones ──
        btnPlayAll.addEventListener('click', function() {{
            if (pares.length > 0) {{
                reproducirParDesde(0);
            }}
        }});

        btnPlayPause.addEventListener('click', function() {{
            if (phase === 'pause') {{
                if (isPaused) {{
                    isPaused = false;
                    btnPlayPause.textContent = '⏸️';
                    const par = obtenerParActual();
                    if (par && pauseTimeout) {{
                        const remaining = parseInt(pauseCountdown.textContent);
                        const startTime = Date.now();
                        pauseTimeout = setInterval(function() {{
                            const elapsed = Date.now() - startTime;
                            const r = Math.max(0, remaining - elapsed);
                            pauseCountdown.textContent = r;
                            const pct = Math.min(((remaining - r) / par.pausa_ms) * 100, 100);
                            playbackProgress.style.width = pct + '%';
                            if (r <= 0) {{
                                clearInterval(pauseTimeout);
                                pauseTimeout = null;
                                reproducirFaseEn();
                            }}
                        }}, 50);
                    }}
                }} else {{
                    isPaused = true;
                    btnPlayPause.textContent = '▶️';
                    if (pauseTimeout) {{
                        clearInterval(pauseTimeout);
                        pauseTimeout = null;
                    }}
                }}
                return;
            }}

            if (!audioElement) return;

            if (isPlaying && !isPaused) {{
                audioElement.pause();
                isPaused = true;
                btnPlayPause.textContent = '▶️';
            }} else if (isPaused) {{
                audioElement.play().then(() => {{
                    isPaused = false;
                    isPlaying = true;
                    btnPlayPause.textContent = '⏸️';
                }}).catch(function(err) {{
                    console.error('Error al reanudar:', err);
                }});
            }}
        }});

        btnStop.addEventListener('click', function() {{
            if (pauseTimeout) {{ clearInterval(pauseTimeout); pauseTimeout = null; }}
            detenerReproduccion();
            ocultarTodasLasFases();
            phase = 'stopped';
            nowPlaying.textContent = 'Reproducción detenida';
            playlistInfo.textContent = '';
            phaseEs.textContent = '🇪🇸 Escuchando español...';
            actualizarResaltado();
        }});

        btnNext.addEventListener('click', function() {{
            if (pauseTimeout) {{ clearInterval(pauseTimeout); pauseTimeout = null; }}
            limpiarAudio();
            avanzarAlSiguiente();
        }});

        btnPrev.addEventListener('click', function() {{
            if (currentIndex > 0) {{
                if (pauseTimeout) {{ clearInterval(pauseTimeout); pauseTimeout = null; }}
                limpiarAudio();
                const prevIdx = currentIndex - 1;
                if (prevIdx < pares.length) {{
                    reproducirParDesde(prevIdx);
                }}
            }}
        }});

        // ── Inicializar ──
        mostrarLista();
    </script>
</body>
</html>'''

    return html
# ── Descarga de frases ──

@app.route('/descargar-frases')
def descargar_frases():
    """Página para seleccionar temas y descargar frases en CSV."""
    return render_template('descargar_frases.html')


@app.route('/api/descargar-frases', methods=['POST'])
def api_descargar_frases():
    """
    Recibe un array de IDs de temas y devuelve un CSV con todas las frases.
    """
    data = request.get_json()
    tema_ids = data.get('tema_ids', [])

    if not tema_ids or not isinstance(tema_ids, list):
        return jsonify({'error': 'Debes especificar al menos un tema.'}), 400

    conn = get_db()

    # Obtener los temas
    placeholders = ','.join('?' * len(tema_ids))
    temas = conn.execute(
        f"SELECT id, name FROM themes WHERE id IN ({placeholders})",
        tema_ids
    ).fetchall()

    if not temas:
        conn.close()
        return jsonify({'error': 'No se encontraron los temas especificados.'}), 404

    # Obtener los pares de audio de todos los temas seleccionados
    pares = conn.execute(
        f"""
        SELECT ap.*, t.name as tema_nombre
        FROM audio_pairs ap
        JOIN themes t ON t.id = ap.theme_id
        WHERE ap.theme_id IN ({placeholders})
        ORDER BY t.name, ap.line_number ASC
        """,
        tema_ids
    ).fetchall()
    conn.close()

    if not pares:
        return jsonify({'error': 'Los temas seleccionados no tienen frases.'}), 404

    # Generar CSV en memoria
    import io
    output = io.StringIO()
    output.write('\ufeff')  # BOM para Excel (UTF-8)
    writer = csv.writer(output)
    writer.writerow(['Tema', 'Línea', 'Español', 'Inglés'])

    for p in pares:
        writer.writerow([p['tema_nombre'], p['line_number'], p['text_es'], p['text_en']])

    csv_content = output.getvalue()
    output.close()

    # Devolver como descarga
    from flask import Response
    return Response(
        csv_content,
        mimetype='text/csv; charset=utf-8',
        headers={
            'Content-Disposition': f'attachment; filename=frases_{datetime.now().strftime("%Y-%m-%d_%H-%M")}.csv',
            'Content-Type': 'text/csv; charset=utf-8'
        }
    )


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
    # Usar el puerto asignado por Back4App ($PORT) o 5000 por defecto
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)
