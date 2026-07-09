"""
Módulo de generación de audio.
Utiliza edge-tts para sintetizar voz en español e inglés.
"""
import asyncio
import os
import re
from config import PREFIJO

try:
    import edge_tts
except ImportError:
    print("Por favor, instala las librerías requeridas ejecutando:")
    print("pip install edge-tts flask")
    import sys
    sys.exit(1)


def limpiar_texto(texto):
    """Sanitiza texto para usarlo como nombre de archivo."""
    texto_limpio = texto.lower()
    texto_limpio = texto_limpio.replace('á', 'a').replace('é', 'e').replace('í', 'i') \
                                .replace('ó', 'o').replace('ú', 'u').replace('ñ', 'n')
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


def calcular_pausa_por_duracion(duracion_segundos):
    """Calcula la pausa en milisegundos basada en la duración del audio en inglés."""
    return int(duracion_segundos * 700)


def generar_audio_linea(es_text, en_text, line_num, output_dir):
    """
    Genera un par de audios (ES + EN) para una línea del CSV.
    Diseñado para ejecutarse en un hilo separado (cada uno con su event loop).
    """
    try:
        texto_formateado = limpiar_texto(es_text)
        base_name = f"{PREFIJO}_{line_num:03d}_{texto_formateado}"
        archivo_es = f"{base_name}_es.mp3"
        archivo_en = f"{base_name}_en.mp3"
        ruta_es = os.path.join(output_dir, archivo_es)
        ruta_en = os.path.join(output_dir, archivo_en)

        # Cada hilo crea su propio event loop para edge-tts (asyncio)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            communicate_es = edge_tts.Communicate(es_text, "es-ES-AlvaroNeural")
            communicate_en = edge_tts.Communicate(en_text, "en-US-GuyNeural")
            loop.run_until_complete(communicate_es.save(ruta_es))
            loop.run_until_complete(communicate_en.save(ruta_en))
        finally:
            loop.close()

        pausa_ms = calcular_pausa_estimada(en_text)
        return {
            'linea': line_num,
            'archivo_es': archivo_es,
            'archivo_en': archivo_en,
            'pausa_ms': pausa_ms,
            'texto_es': es_text,
            'texto_en': en_text
        }, None
    except Exception as e:
        # Limpiar archivos parciales si falló
        try:
            if os.path.exists(ruta_es):
                os.remove(ruta_es)
            if os.path.exists(ruta_en):
                os.remove(ruta_en)
        except Exception:
            pass
        return None, {'linea': line_num, 'texto': es_text, 'error': str(e)}