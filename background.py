"""
Sistema de tareas en segundo plano (background tasks).
Permite lanzar generación de audios en hilos separados
y hacer polling del progreso.
"""
import asyncio
import csv
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from audio_generator import generar_audio_linea, limpiar_texto
from database import guardar_pares_en_bd, guardar_csv_file

# ── Estado global de tareas (thread-safe) ──
background_tasks = {}
tasks_lock = threading.Lock()

# Pool de hilos para tareas en segundo plano
executor = None


def init_background(max_workers=3):
    """Inicializa el sistema de background tasks."""
    global executor
    executor = ThreadPoolExecutor(max_workers=max_workers)


def crear_task(tema_id, tema_nombre, tema_dir):
    """Crea una nueva tarea y devuelve su ID."""
    task_id = str(uuid.uuid4())
    with tasks_lock:
        background_tasks[task_id] = {
            'estado': 'iniciando',
            'progreso': 0,
            'total': 0,
            'resultados': [],
            'errores': [],
            'error_global': None,
            'tema_id': tema_id,
            'tema_nombre': tema_nombre,
            'tema_dir': tema_dir
        }
    return task_id


def lanzar_procesamiento(task_id, csv_path, output_dir, tema_id, tema_nombre, nombre_archivo_original, app):
    """Lanza el procesamiento CSV en el pool de hilos."""
    if executor is None:
        init_background()
    executor.submit(
        _ejecutar_procesamiento_csv,
        task_id, csv_path, output_dir, tema_id, tema_nombre,
        nombre_archivo_original, app
    )


def obtener_progreso_task(task_id):
    """Obtiene el progreso actual de una tarea."""
    with tasks_lock:
        task = background_tasks.get(task_id)
        if task is None:
            return None
        # Devolver copia para evitar race conditions
        return dict(task)


def limpiar_task(task_id):
    """Elimina una tarea completada."""
    with tasks_lock:
        if task_id in background_tasks:
            del background_tasks[task_id]


def _ejecutar_procesamiento_csv(task_id, csv_path, output_dir, tema_id, tema_nombre,
                                 nombre_archivo_original, app):
    """Ejecuta la generación de audios en un hilo separado y actualiza el progreso."""
    try:
        # Leer CSV
        filas = []
        with open(csv_path, mode='r', encoding='utf-8') as f:
            reader = csv.reader(f, delimiter=';')
            next(reader, None)  # Saltar cabecera
            for index, row in enumerate(reader):
                if len(row) >= 2:
                    es_text = row[0].strip()
                    en_text = row[1].strip()
                    if es_text and en_text:
                        filas.append((es_text, en_text, index + 1))

        total = len(filas)
        with tasks_lock:
            bg = background_tasks.get(task_id)
            if bg:
                bg['total'] = total
                bg['estado'] = 'procesando'

        # Procesar líneas concurrentemente con ThreadPoolExecutor
        resultados = []
        errores = []
        batch_size = min(5, max(1, app.config.get('MAX_WORKERS', 3)))

        with ThreadPoolExecutor(max_workers=batch_size) as batch_executor:
            futures = []
            for es_text, en_text, line_num in filas:
                future = batch_executor.submit(
                    generar_audio_linea, es_text, en_text, line_num, output_dir
                )
                futures.append(future)

            for i, future in enumerate(as_completed(futures)):
                resultado, error = future.result()
                if resultado:
                    resultados.append(resultado)
                if error:
                    errores.append(error)

                # Actualizar progreso
                with tasks_lock:
                    bg = background_tasks.get(task_id)
                    if bg:
                        bg['progreso'] = i + 1
                        bg['resultados'] = resultados[:]
                        bg['errores'] = errores[:]

        # Guardar en BD
        if resultados:
            guardar_pares_en_bd(app, tema_id, resultados)
            guardar_csv_file(app, tema_id, nombre_archivo_original)

        # Marcar como completado
        with tasks_lock:
            bg = background_tasks.get(task_id)
            if bg:
                bg['estado'] = 'completado'
                bg['progreso'] = total
                bg['resultados'] = resultados[:]
                bg['errores'] = errores[:]

    except Exception as e:
        with tasks_lock:
            bg = background_tasks.get(task_id)
            if bg:
                bg['estado'] = 'error'
                bg['error_global'] = str(e)
    finally:
        # Limpiar CSV temporal
        if os.path.exists(csv_path):
            os.remove(csv_path)