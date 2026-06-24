import asyncio
import csv
import os
import re
import sys
import tempfile
import shutil
from datetime import datetime
from werkzeug.utils import secure_filename

import glob
import io
from flask import Flask, render_template, request, jsonify, send_from_directory, send_file, abort
from mutagen.mp3 import MP3

try:
    import edge_tts
    from pydub import AudioSegment
    from pydub.silence import detect_nonsilent
except ImportError:
    print("Por favor, instala las librerías requeridas ejecutando:")
    print("pip install edge-tts pydub flask")
    print("Nota: pydub también requiere tener instalado FFmpeg en el sistema.")
    sys.exit(1)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max upload
app.config['UPLOAD_FOLDER'] = tempfile.gettempdir()

PREFIJO = "audio"

# ──────────────────────────────────────────────
#  Funciones del núcleo (extraídas de traducciones.py)
# ──────────────────────────────────────────────

def limpiar_texto(texto):
    """Sanitiza texto para usarlo como nombre de archivo."""
    texto_limpio = texto.lower()
    texto_limpio = texto_limpio.replace('á', 'a').replace('é', 'e').replace('í', 'i').replace('ó', 'o').replace('ú', 'u').replace('ñ', 'n')
    texto_limpio = re.sub(r'[^a-z0-9]', '_', texto_limpio)
    texto_limpio = re.sub(r'_+', '_', texto_limpio)
    return texto_limpio.strip('_')


def obtener_duracion_real(audio, silencio_thresh=-50, min_silencio_len=100):
    """
    Calcula la duración del audio ignorando los silencios iniciales y finales.
    The Silence Gap Formula: mide el tiempo neto de voz.
    """
    tramos_con_voz = detect_nonsilent(audio, min_silence_len=min_silencio_len, silence_thresh=silencio_thresh)

    if tramos_con_voz:
        inicio_real = tramos_con_voz[0][0]
        final_real = tramos_con_voz[-1][1]
        return final_real - inicio_real

    return len(audio)


async def generar_audios_desde_csv(csv_path, output_dir, progreso_callback=None):
    """
    Procesa el CSV y genera los audios.
    progreso_callback: función que recibe dict con info de progreso.
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

            temp_es = os.path.join(output_dir, f"temp_es_{line_num}.mp3")
            temp_en = os.path.join(output_dir, f"temp_en_{line_num}.mp3")

            try:
                communicate_es = edge_tts.Communicate(es_text, "es-ES-AlvaroNeural")
                communicate_en = edge_tts.Communicate(en_text, "en-US-GuyNeural")

                await communicate_es.save(temp_es)
                await communicate_en.save(temp_en)

                audio_es = AudioSegment.from_mp3(temp_es)
                audio_en = AudioSegment.from_mp3(temp_en)

                duracion_silencio_ms = obtener_duracion_real(audio_en)
                silencio = AudioSegment.silent(duration=duracion_silencio_ms)

                line_audio = audio_es + silencio + audio_en

                texto_formateado = limpiar_texto(es_text)
                output_file = f"{PREFIJO}_{line_num}_{texto_formateado}.mp3"
                output_path = os.path.join(output_dir, output_file)

                line_audio.export(output_path, format="mp3")

                # Limpiar temporales
                for tmp in [temp_es, temp_en]:
                    if os.path.exists(tmp):
                        os.remove(tmp)

                resultados.append({
                    'linea': line_num,
                    'archivo': output_file,
                    'silencio_ms': duracion_silencio_ms
                })

                if progreso_callback:
                    progreso_callback({
                        'linea': line_num,
                        'es_text': es_text,
                        'en_text': en_text,
                        'estado': 'completado',
                        'archivo': output_file
                    })

            except Exception as e:
                errores.append({
                    'linea': line_num,
                    'texto': es_text,
                    'error': str(e)
                })
                # Limpiar temporales si falló
                for tmp in [temp_es, temp_en]:
                    if os.path.exists(tmp):
                        os.remove(tmp)

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


@app.route('/generar')
def generar():
    """Formulario para generar audios."""
    return render_template('generar.html')


@app.route('/procesar', methods=['POST'])
def procesar():
    """
    Endpoint que recibe el CSV y la carpeta de salida, y genera los audios.
    """
    # Validar que se haya subido un archivo
    if 'csv_file' not in request.files:
        return jsonify({'success': False, 'error': 'No se envió ningún archivo CSV.'}), 400

    file = request.files['csv_file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'El nombre del archivo está vacío.'}), 400

    if not file.filename.lower().endswith('.csv'):
        return jsonify({'success': False, 'error': 'El archivo debe ser un CSV.'}), 400

    output_dir = request.form.get('output_dir', '').strip()
    if not output_dir:
        return jsonify({'success': False, 'error': 'Debes especificar una carpeta de salida.'}), 400

    # Asegurar que la carpeta de salida existe
    if not os.path.isdir(output_dir):
        try:
            os.makedirs(output_dir, exist_ok=True)
        except Exception as e:
            return jsonify({'success': False, 'error': f'No se pudo crear la carpeta de salida: {e}'}), 400

    # Guardar el CSV subido a una ubicación temporal
    csv_filename = secure_filename(file.filename)
    csv_path = os.path.join(app.config['UPLOAD_FOLDER'], csv_filename)
    file.save(csv_path)

    # Procesar los audios
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        resultados, errores = loop.run_until_complete(
            generar_audios_desde_csv(csv_path, output_dir)
        )
        loop.close()
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error durante la generación: {e}'}), 500
    finally:
        # Limpiar CSV temporal
        if os.path.exists(csv_path):
            os.remove(csv_path)

    # Preparar respuesta
    response = {
        'success': True,
        'total': len(resultados),
        'errores': len(errores),
        'resultados': resultados,
        'carpeta_salida': output_dir
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


# ──────────────────────────────────────────────
#  Rutas para el reproductor de audios
# ──────────────────────────────────────────────

@app.route('/reproducir')
def reproducir():
    """Página del reproductor de audios."""
    return render_template('reproducir.html')


@app.route('/listar_audios', methods=['POST'])
def listar_audios():
    """
    Escanea un directorio en busca de archivos MP3, los ordena por nombre
    y devuelve sus metadatos (nombre, duración).
    """
    data = request.get_json()
    directorio = data.get('directorio', '').strip()

    if not directorio:
        return jsonify({'success': False, 'error': 'Debes especificar un directorio.'}), 400

    if not os.path.isdir(directorio):
        return jsonify({'success': False, 'error': f'El directorio no existe: {directorio}'}), 400

    try:
        # Buscar todos los MP3 en el directorio
        patron = os.path.join(directorio, '*.mp3')
        archivos = sorted(glob.glob(patron), key=lambda x: os.path.basename(x).lower())

        lista = []
        for ruta in archivos:
            nombre = os.path.basename(ruta)
            try:
                audio = MP3(ruta)
                duracion_segundos = audio.info.length if audio.info else 0
            except Exception:
                duracion_segundos = 0

            lista.append({
                'nombre': nombre,
                'ruta': ruta,
                'duracion_segundos': round(duracion_segundos, 1)
            })

        return jsonify({
            'success': True,
            'directorio': directorio,
            'total': len(lista),
            'archivos': lista
        })

    except Exception as e:
        return jsonify({'success': False, 'error': f'Error al escanear el directorio: {e}'}), 500


@app.route('/servir_audio')
def servir_audio():
    """
    Sirve un archivo de audio individual para su reproducción en el navegador.
    """
    directorio = request.args.get('directorio', '').strip()
    archivo = request.args.get('archivo', '').strip()

    if not directorio or not archivo:
        abort(400, description='Faltan parámetros: directorio y archivo son requeridos.')

    # Normalizar ruta
    directorio = os.path.normpath(directorio)
    archivo = os.path.basename(archivo)

    if not os.path.isdir(directorio):
        abort(400, description='El directorio no existe.')

    if not archivo.lower().endswith('.mp3'):
        abort(400, description='Solo se permiten archivos MP3.')

    # Validar path traversal
    ruta_completa = os.path.normpath(os.path.join(directorio, archivo))
    if not ruta_completa.startswith(os.path.normpath(directorio)):
        abort(403, description='Acceso denegado.')

    if not os.path.isfile(ruta_completa):
        abort(404, description='Archivo no encontrado.')

    return send_file(ruta_completa, mimetype='audio/mpeg', conditional=True)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
