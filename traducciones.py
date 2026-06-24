import asyncio
import csv
import os
import re

try:
    import edge_tts
    from pydub import AudioSegment
    from pydub.silence import detect_nonsilent  # <-- Nueva herramienta para detectar silencio
except ImportError:
    print("Por favor, instala las librerías requeridas ejecutando:")
    print("pip install edge-tts pydub")
    print("Nota: pydub también requiere tener instalado FFmpeg en el sistema.")
    exit(1)

PREFIJO = "audio"

def limpiar_texto(texto):
    texto_limpio = texto.lower()
    texto_limpio = texto_limpio.replace('á', 'a').replace('é', 'e').replace('í', 'i').replace('ó', 'o').replace('ú', 'u').replace('ñ', 'n')
    texto_limpio = re.sub(r'[^a-z0-9]', '_', texto_limpio)
    texto_limpio = re.sub(r'_+', '_', texto_limpio)
    return texto_limpio.strip('_')

def obtener_duracion_real(audio, silencio_thresh=-50, min_silencio_len=100):
    """
    Calcula la duración del audio ignorando los silencios iniciales y finales.
    silencio_thresh: El umbral en dBFS para considerar algo como 'silencio' (Default: -50)
    """
    # Detecta los tramos donde SÍ hay sonido
    tramos_con_voz = detect_nonsilent(audio, min_silence_len=min_silencio_len, silence_thresh=silencio_thresh)
    
    if tramos_con_voz:
        # El inicio del primer tramo con voz
        inicio_real = tramos_con_voz[0][0]
        # El final del último tramo con voz
        final_real = tramos_con_voz[-1][1]
        # La duración real es la diferencia
        return final_real - inicio_real
    
    # Si por algún motivo no detecta voz (archivo vacío), devolvemos la duración total por seguridad
    return len(audio)

async def main():
    csv_file = 'traducciones.csv'
    if not os.path.exists(csv_file):
        print(f"No se encontró el archivo {csv_file}. Asegúrate de tenerlo en el mismo directorio.")
        return

    print("Iniciando generación con ajuste de silencios optimizado...")

    with open(csv_file, mode='r', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader, None)
        
        for index, row in enumerate(reader):
            if len(row) < 2:
                continue
                
            es_text = row[0].strip()
            en_text = row[1].strip()
            
            line_num = index + 1
            print(f"Procesando línea {line_num}: '{es_text}' -> '{en_text}'")
            
            temp_es = f"temp_es_{line_num}.mp3"
            temp_en = f"temp_en_{line_num}.mp3"
            
            communicate_es = edge_tts.Communicate(es_text, "es-ES-AlvaroNeural")
            communicate_en = edge_tts.Communicate(en_text, "en-US-GuyNeural")
            
            await communicate_es.save(temp_es)
            await communicate_en.save(temp_en)
            
            audio_es = AudioSegment.from_mp3(temp_es)
            audio_en = AudioSegment.from_mp3(temp_en)
            
            # --- AQUÍ ESTÁ EL CAMBIO CLAVE ---
            # En vez de 'len(audio_en)', medimos el tiempo neto de voz en inglés
            duracion_silencio_ms = obtener_duracion_real(audio_en)
            
            silencio = AudioSegment.silent(duration=duracion_silencio_ms)
            
            # Estructura final: Español + Silencio Ajustado + Inglés
            line_audio = audio_es + silencio + audio_en
            
            texto_formateado = limpiar_texto(es_text)
            output_file = f"{PREFIJO}_{line_num}_{texto_formateado}.mp3"
            
            line_audio.export(output_file, format="mp3")
            print(f" -> Guardado (Silencio ajustado a {duracion_silencio_ms}ms): {output_file}")
            
            os.remove(temp_es)
            os.remove(temp_en)
            
    print("\n¡Proceso completado! Los espacios en blanco ahora son mucho más naturales.")

if __name__ == "__main__":
    asyncio.run(main())