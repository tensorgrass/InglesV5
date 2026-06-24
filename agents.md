> **⚠️ Mantenimiento:** Este archivo debe actualizarse siempre que se añadan nuevas funcionalidades, cambios arquitectónicos o decisiones técnicas importantes al proyecto. Mantén esta documentación viva y sincronizada con el código.

---

## Arquitectura del Proyecto

```
InglesV5/
├── app.py                   → Aplicación Flask (punto de entrada web)
├── traducciones.py          → Script original de línea de comandos (conservado)
├── traducciones.csv         → CSV de ejemplo con frases español/inglés
├── templates/
│   ├── index.html           → Página principal con menú de navegación
│   ├── generar.html         → Formulario para subir CSV y generar audios
│   └── reproducir.html      → Reproductor de audios con lista de reproducción
├── static/
│   └── style.css            → Estilos CSS con diseño responsive
└── agents.md                → Documentación del proyecto
```

### 1. Migración a Flask (Web GUI)

El proyecto ahora cuenta con una interfaz web basada en **Flask** que expone las mismas funcionalidades del script original a través de un navegador.

#### 1.1 Rutas de la aplicación

| Ruta | Método | Descripción |
|------|--------|-------------|
| `/` | GET | Página principal con menú y explicación de uso |
| `/generar` | GET | Formulario para subir CSV y especificar carpeta de salida |
| `/procesar` | POST | Endpoint que recibe el CSV + carpeta de salida y genera los audios |
| `/descargar/<filename>` | GET | Descarga un archivo de audio individual desde la carpeta de salida |
| `/reproducir` | GET | Reproductor de audios con lista de reproducción |
| `/listar_audios` | POST | Escanea un directorio, lista los MP3 ordenados por nombre con su duración |
| `/servir_audio` | GET | Sirve un archivo MP3 individual para reproducción en el navegador |

#### 1.2 Flujo de trabajo

1. El usuario accede a `http://localhost:5000/` en el navegador.
2. Hace clic en **"Generar Audios"** → formulario en `/generar`.
3. Adjunta un archivo CSV y escribe la ruta de la carpeta de salida.
4. El formulario envía los datos vía `POST` a `/procesar` usando `FormData`.
5. El endpoint `/procesar` valida el archivo y la carpeta, y ejecuta la generación.
6. Devuelve un JSON con `success`, `total`, `resultados` y `errores`.
7. El frontend muestra una barra de progreso y el listado de archivos generados.

#### 1.3 Validaciones implementadas

- Archivo CSV obligatorio y con extensión `.csv`.
- Carpeta de salida obligatoria; se crea automáticamente si no existe.
- Límite de subida: 16 MB (`MAX_CONTENT_LENGTH`).
- Manejo de errores por línea (fallo de TTS, archivo corrupto, etc.) sin detener el proceso completo.

---

### 2. Núcleo de generación (compartido entre CLI y Flask)

Tanto `traducciones.py` como `app.py` comparten la misma lógica central, que se ha encapsulado en funciones reutilizables dentro de `app.py`:

#### 2.1 `limpiar_texto(texto)`
Sanitiza el texto español para usarlo como nombre de archivo, siguiendo las reglas de la convención de nombres (ver sección 4).

#### 2.2 `obtener_duracion_real(audio, silencio_thresh=-50, min_silencio_len=100)`
Implementa **The Silence Gap Formula** (ver sección 3).

#### 2.3 `generar_audios_desde_csv(csv_path, output_dir, progreso_callback=None)`
Función asíncrona que:
- Lee el CSV fila por fila.
- Genera audio TTS para español (`es-ES-AlvaroNeural`) e inglés (`en-US-GuyNeural`) usando `edge-tts`.
- Mide el silencio real del audio en inglés.
- Concatena: `[español] + [silencio ajustado] + [inglés]`.
- Exporta el resultado como MP3 y elimina los temporales.
- Acepta un callback opcional para notificar progreso en tiempo real.
- Reporta errores por línea sin interrumpir el procesamiento.

---

### 3. The Silence Gap Formula

Initially, using the absolute duration of the English audio introduced an over-extended gap due to natural audio padding added by TTS engines.
- **Solution implemented:** `pydub.silence.detect_nonsilent`.
- **Mechanism:** The script measures the net speech duration of the English clip by setting a noise threshold (default: `-50 dBFS`). It identifies the exact millisecond where active pronunciation starts and ends. The resulting gap duration equals this *net vocal activity time*, creating an optimal active-recall response window.

---

### 4. Output File Naming Convention

Files must be exported individually using a strict sanitized pattern:
`{PREFIJO}_{Numero_Linea}_{Texto_Columna_1_Sanitizado}.mp3`

### Sanitization Rules (`limpiar_texto`):
1. Convert all characters to lowercase.
2. Flatten common Spanish diacritics/accents to ASCII equivalents (`á`->`a`, `é`->`e`, `í`->`i`, `ó`->`o`, `ú`->`u`, `ñ`->`n`).
3. Strip any non-alphanumeric character and replace it with a single underscore (`_`).
4. Prevent sequential underscores (e.g., `__` becomes `_`) and trim leading/trailing underscores.

---

### 5. Dependencias del proyecto

```
pip install flask edge-tts pydub mutagen
```

**Nota:** `pydub` también requiere tener instalado **FFmpeg** en el sistema. `mutagen` se usa para obtener la duración de los MP3 en el reproductor.

---

### 6. Ejecución

```bash
# Modo servidor web (Flask)
python app.py
# Abrir en navegador: http://localhost:5000

# Modo línea de comandos (original)
python traducciones.py
```

El servidor Flask se ejecuta en `http://0.0.0.0:5000` con modo debug activado.

---

### 7. Reference Code Implementation

El código de referencia original se encuentra en `traducciones.py`. La implementación Flask en `app.py` extiende esa misma lógica añadiendo una interfaz web y manteniendo compatibilidad total con el formato CSV y la convención de nombres existente.

---

### 8. Reproductor de Audios

A partir de la versión con Flask, se ha añadido un reproductor de audio integrado en el navegador, accesible desde el menú principal como **"Reproducir Audios"**.

#### 8.1 Flujo de reproducción

1. El usuario introduce la ruta de un directorio que contiene archivos MP3.
2. La aplicación escanea el directorio, ordena los archivos alfabéticamente por nombre y obtiene la duración de cada MP3 usando `mutagen`.
3. Se muestra una lista de reproducción con todos los archivos encontrados y su duración.
4. El usuario puede:
   - **Reproducir todo** desde el principio.
   - **Hacer clic** en cualquier archivo de la lista para empezar desde ahí.
   - Usar los controles de transporte: **Anterior (⏮️)**, **Reproducir/Pausar (▶️/⏸️)**, **Parar (⏹️)**, **Siguiente (⏭️)**.
5. Al finalizar un archivo, el reproductor avanza automáticamente al siguiente.
6. Una barra de progreso muestra el avance de la reproducción, y el archivo activo se resalta en la lista.

#### 8.2 Nuevas rutas

| Ruta | Método | Descripción |
|------|--------|-------------|
| `/reproducir` | GET | Página del reproductor de audios |
| `/listar_audios` | POST | Escanea un directorio buscando `*.mp3`, los ordena por nombre y devuelve nombre + duración |
| `/servir_audio` | GET | Sirve un archivo MP3 individual para el reproductor del navegador (con validación anti path traversal) |

#### 8.3 Controles del reproductor

El frontend (`templates/reproducir.html`) gestiona todo el estado del reproductor en JavaScript:
- `audioFiles[]`: array con la lista de archivos obtenida del servidor.
- `currentIndex`: índice del archivo actual.
- `audioElement`: objeto `Audio` de HTML5 para la reproducción.
- **Reproducir/Pausar**: alterna entre reproducción y pausa sin perder la posición.
- **Parar**: detiene la reproducción y reinicia la posición a 0.
- **Anterior/Siguiente**: navega por la lista de reproducción.
- Al hacer clic en un archivo de la lista, se salta directamente a esa posición.
- El archivo activo se resalta visualmente y se hace scroll automático.

#### 8.4 Validaciones de seguridad

- El endpoint `/listar_audios` verifica que el directorio exista antes de escanear.
- El endpoint `/servir_audio` normaliza la ruta y comprueba que el archivo solicitado esté dentro del directorio permitido (protección contra path traversal).
- Solo se sirven archivos con extensión `.mp3`.