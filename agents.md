> **⚠️ Mantenimiento:** Este archivo debe actualizarse siempre que se añadan nuevas funcionalidades, cambios arquitectónicos o decisiones técnicas importantes al proyecto. Mantén esta documentación viva y sincronizada con el código.

---

## Arquitectura del Proyecto

```
InglesV5/
├── app.py                   → Aplicación Flask (punto de entrada web)
├── config.py                → Configuración centralizada (Secret Key, rutas, límites)
├── database.py              → Módulo de base de datos SQLite (CRUD temas/pares/CSVs)
├── background.py            → Sistema de tareas en segundo plano (ThreadPoolExecutor)
├── audio_generator.py       → Núcleo de generación TTS (edge-tts, sanitización, pausas)
├── traducciones.py          → Script original de línea de comandos (conservado)
├── traducciones.csv         → CSV de ejemplo con frases español/inglés
├── database.db              → Base de datos SQLite (temas, pares de audio, CSVs)
├── requirements.txt         → Dependencias del proyecto
├── Dockerfile               → Configuración Docker para Back4App
├── .dockerignore            → Exclusiones para Docker
├── templates/
│   ├── index.html           → Página principal con menú de navegación
│   ├── generar.html         → Formulario para subir CSV y generar audios por tema
│   ├── reproducir.html      → Reproductor secuencial ES → pausa → EN
│   ├── temas.html           → Gestión de temas (CRUD)
│   ├── exportar.html        → Exportación de temas con reproductor offline
│   └── descargar_frases.html→ Descarga de frases en CSV
├── routes/
│   ├── __init__.py          → Paquete de rutas Flask
│   ├── main.py              → Ruta principal (/) y archivos de audio estáticos
│   ├── temas.py             → CRUD de temas (/api/temas, /temas)
│   ├── generar.py           → Generación de audios (/generar, /procesar, /progreso)
│   ├── reproductor.py       → Reproductor de audios (/reproducir, /listar_audios, /servir_audio)
│   ├── exportar.py          → Exportación offline (/exportar, /api/exportar)
│   └── descargas.py         → Descarga de frases CSV (/descargar-frases, /api/descargar-frases)
├── static/
│   ├── style.css            → Estilos CSS con diseño responsive
│   └── audio/               → Directorio con subcarpetas por tema
├── csv/                     → Archivos CSV de ejemplo subidos
├── offline/                 → Exportaciones offline de temas
└── agents.md                → Documentación del proyecto
```

---

### 1. Arquitectura de la aplicación Flask

El proyecto ha sido reestructurado de una aplicación Flask monolítica a una arquitectura modular con separación de responsabilidades.

#### 1.1 Punto de entrada (`app.py`)

`app.py` es el punto de entrada principal y se limita a:
- Configurar la aplicación Flask desde `config.py`
- Inicializar la base de datos (`database.py`)
- Inicializar el sistema de background tasks (`background.py`)
- Registrar los módulos de rutas desde `routes/`
- Iniciar el servidor

Ya no contiene lógica de rutas ni de generación de audio.

#### 1.2 Configuración centralizada (`config.py`)

Todas las constantes de configuración están en `config.py`:
- `SECRET_KEY`, `MAX_CONTENT_LENGTH` (16 MB), `MAX_WORKERS` (3)
- Métodos estáticos para rutas de audio y base de datos
- Constante `PREFIJO = "audio"` para la convención de nombres

#### 1.3 Enrutamiento modular

Las rutas están organizadas en módulos separados dentro de `routes/`:

| Módulo | Funcionalidad |
|--------|---------------|
| `routes/main.py` | Página de inicio, servir archivos de audio estáticos |
| `routes/temas.py` | CRUD completo de temas con API REST |
| `routes/generar.py` | Generación asíncrona de audios con polling de progreso |
| `routes/reproductor.py` | Reproductor de pares ES/EN con pausa programática |
| `routes/exportar.py` | Exportación de temas a directorio con reproductor HTML offline |
| `routes/descargas.py` | Descarga de frases de múltiples temas en CSV |

---

### 2. Base de datos SQLite (`database.py`)

La base de datos almacena temas, pares de audio y archivos CSV subidos.

#### 2.1 Esquema de tablas

- **`themes`**: Temas con nombre único, descripción y timestamps.
- **`audio_pairs`**: Pares ES/EN con números de línea, archivos generados y pausa calculada.
- **`csv_files`**: Registro de archivos CSV subidos por tema.

#### 2.2 Operaciones principales

| Función | Descripción |
|---------|-------------|
| `crear_tema(app, nombre, descripcion)` | Crea o actualiza un tema |
| `guardar_pares_en_bd(app, tema_id, resultados)` | Guarda resultados de generación |
| `listar_temas_db(app)` | Lista temas con conteo de pares |
| `listar_temas_con_pares(app)` | Lista solo temas que tienen pares |
| `obtener_tema_db(app, tema_id)` | Tema + sus pares de audio |
| `actualizar_tema_db(app, tema_id, nombre, descripcion)` | Actualiza nombre/descripción |
| `eliminar_tema_db(app, tema_id)` | Elimina tema de la BD |
| `obtener_pares_por_temas(app, tema_ids)` | Pares de múltiples temas para exportación |
| `guardar_csv_file(app, tema_id, filename)` | Registra CSV subido |

---

### 3. Sistema de Background Tasks (`background.py`)

Permite lanzar la generación de audios en segundo plano y hacer polling del progreso desde el frontend.

#### 3.1 Flujo de trabajo asíncrono

1. El frontend envía el CSV y nombre del tema a `/procesar`
2. Se crea una tarea con un `task_id` UUID único
3. El procesamiento se lanza en un `ThreadPoolExecutor`
4. El endpoint responde inmediatamente con el `task_id`
5. El frontend hace polling a `/progreso/<task_id>` para seguir el avance
6. Al completarse, se devuelven resultados y errores, y la tarea se limpia

#### 3.2 Estados de tarea

- `iniciando` → `procesando` → `completado` | `error`

#### 3.3 Thread safety

- Las tareas se almacenan en un diccionario global protegido con `threading.Lock`
- Cada línea del CSV se procesa en un hilo separado (pool de hasta `MAX_WORKERS` hilos)

---

### 4. Núcleo de generación de audio (`audio_generator.py`)

Lógica compartida entre generación online y offline, extraída como módulo independiente.

#### 4.1 `limpiar_texto(texto)`
Sanitiza el texto español para usarlo como nombre de archivo (ver sección 5).

#### 4.2 `calcular_pausa_estimada(texto_en)`
Heurística basada en número de palabras (~150ms por palabra + 300ms base, mínimo 800ms).

#### 4.3 `calcular_pausa_por_duracion(duracion_segundos)`
Aproximación del 70% de la duración del audio en inglés.

#### 4.4 `generar_audio_linea(es_text, en_text, line_num, output_dir)`
Función diseñada para ejecutarse en un hilo:
- Crea su propio event loop asyncio (cada hilo necesita el suyo)
- Genera audio TTS con `edge-tts` (español: `es-ES-AlvaroNeural`, inglés: `en-US-GuyNeural`)
- Guarda archivos ES y EN separados
- Calcula pausa estimada
- Limpia archivos parciales si falla

---

### 5. Rutas de la aplicación

#### 5.1 Rutas principales (`routes/main.py`)

| Ruta | Método | Descripción |
|------|--------|-------------|
| `/` | GET | Página principal con menú y explicación de uso |
| `/static/audio/<path:filename>` | GET | Sirve archivos de audio estáticos |

#### 5.2 Gestión de temas (`routes/temas.py`)

| Ruta | Método | Descripción |
|------|--------|-------------|
| `/temas` | GET | Página de gestión de temas |
| `/api/temas` | GET | Lista todos los temas con metadatos |
| `/api/temas/<int:tema_id>` | GET | Obtiene un tema con sus pares de audio |
| `/api/temas` | POST | Crea un nuevo tema |
| `/api/temas/<int:tema_id>` | PUT | Actualiza nombre/descripción de un tema |
| `/api/temas/<int:tema_id>` | DELETE | Elimina un tema y sus archivos de audio |

#### 5.3 Generación de audios (`routes/generar.py`)

| Ruta | Método | Descripción |
|------|--------|-------------|
| `/generar` | GET | Formulario para generar audios |
| `/procesar` | POST | Recibe CSV + tema y lanza generación asíncrona |
| `/progreso/<task_id>` | GET | Polling de progreso de tarea asíncrona |
| `/descargar/<path:filename>` | GET | Descarga un archivo de audio individual |

#### 5.4 Reproductor de audios (`routes/reproductor.py`)

| Ruta | Método | Descripción |
|------|--------|-------------|
| `/reproducir` | GET | Página del reproductor de audios |
| `/listar_audios` | POST | Escanea un tema, lista pares ES/EN con duración |
| `/servir_audio` | GET | Sirve un MP3 individual (con anti path traversal) |

#### 5.5 Exportación offline (`routes/exportar.py`)

| Ruta | Método | Descripción |
|------|--------|-------------|
| `/exportar` | GET | Página para exportar un tema |
| `/api/exportar` | POST | Exporta tema: copia audios + genera HTML offline |

#### 5.6 Descarga de frases (`routes/descargas.py`)

| Ruta | Método | Descripción |
|------|--------|-------------|
| `/descargar-frases` | GET | Página para seleccionar temas y descargar CSV |
| `/api/descargar-frases` | POST | Recibe IDs de temas, devuelve CSV con frases |

---

### 6. Flujo de trabajo (generación asíncrona)

1. El usuario accede a `http://localhost:5000/generar`.
2. Selecciona un tema existente o escribe uno nuevo, adjunta un CSV.
3. El formulario envía los datos vía `POST` a `/procesar` usando `FormData`.
4. El endpoint `/procesar` valida, crea/recupera el tema, y lanza el procesamiento en segundo plano.
5. Devuelve un `task_id` inmediatamente.
6. El frontend hace polling a `/progreso/<task_id>` cada 1-2 segundos.
7. Para cada línea del CSV, se genera un par de archivos MP3:
   - `{PREFIJO}_{LINEA}_{TEXTO_SANITIZADO}_es.mp3` (voz española)
   - `{PREFIJO}_{LINEA}_{TEXTO_SANITIZADO}_en.mp3` (voz inglesa)
8. Al completarse, los resultados se guardan en la base de datos y la tarea se limpia.

---

### 7. Exportación offline (`routes/exportar.py`)

Permite exportar un tema completo a un directorio con:
- Todos los archivos MP3 copiados
- Un archivo HTML autónomo que funciona completamente offline
- El HTML generado incluye el mismo reproductor con pausa programática, barra de progreso, controles de transporte y lista de reproducción
- Todo el JavaScript está embebido en el propio HTML

---

### 8. Descarga de frases en CSV (`routes/descargas.py`)

Permite seleccionar múltiples temas y descargar todas sus frases en un único archivo CSV:
- Columnas: Tema, Línea, Español, Inglés
- Incluye BOM UTF-8 para compatibilidad con Excel
- Nombre de archivo con timestamp

---

### 9. Pausa programática en el navegador

Los audios se generan por separado (ES y EN independientes). La pausa entre español e inglés se calcula programáticamente:

- Durante la generación: `calcular_pausa_estimada` (~150ms por palabra, mínimo 800ms)
- En el reproductor: se usa la pausa almacenada en la BD para cada par

Flujo de reproducción secuencial:
1. 🇪🇸 **Español** → se reproduce el audio en español.
2. ⏸️ **Pausa** → se muestra un contador regresivo con la pausa calculada.
3. 🇬🇧 **Inglés** → se reproduce el audio en inglés.
4. ✅ **Completado** → se avanza automáticamente al siguiente par.

### 10. Precarga de audios en memoria (Blob URLs)

Para evitar latencias de red en la reproducción secuencial, al cargar un tema se precargan **todos los audios en memoria** mediante Blob URLs.

#### 10.1 Funcionamiento

1. Cuando el usuario selecciona un tema y hace clic en "Cargar Audios", el frontend:
   - Obtiene la lista de pares ES/EN desde `/listar_audios`
   - Llama a `precargarAudios()` que descarga cada MP3 como `ArrayBuffer` mediante `fetch`
   - Convierte cada buffer en un `Blob` con tipo `audio/mpeg`
   - Crea una `blobUrl` usando `URL.createObjectURL(blob)` y la almacena en el objeto del par (`p.es.blobUrl`, `p.en.blobUrl`)

2. Durante la reproducción, las funciones `reproducirFaseEs()`, `reproducirFaseEn()` y `reproducirArchivoSuelto()` usan la `blobUrl` si está disponible, con fallback a `/servir_audio` si la precarga falló o aún no terminó.

3. Al cambiar de tema, `liberarBlobUrls()` recorre todos los pares y sueltos llamando a `URL.revokeObjectURL()` para liberar memoria.

#### 10.2 Concurrencia

- Las descargas se lanzan en lotes de **6 peticiones simultáneas** (`CONCURRENCIA = 6`)
- Errores individuales se ignoran (el audio correspondiente usará el fallback a `/servir_audio`)
- La UI muestra progreso: `⏳ Precargando X/Y audios...`

#### 10.3 Variables involucradas

| Variable | Descripción |
|----------|-------------|
| `pares[].es.blobUrl` | Blob URL del audio en español |
| `pares[].en.blobUrl` | Blob URL del audio en inglés |
| `sueltos[].blobUrl` | Blob URL de archivo suelto |
| `CONCURRENCIA` | Límite de descargas simultáneas (6) |

---

### 11. Output File Naming Convention

Files must be exported individually using a strict sanitized pattern:
`{PREFIJO}_{Numero_Linea}_{Texto_Columna_1_Sanitizado}_es.mp3`
`{PREFIJO}_{Numero_Linea}_{Texto_Columna_1_Sanitizado}_en.mp3`

### Sanitization Rules (`limpiar_texto`):
1. Convert all characters to lowercase.
2. Flatten common Spanish diacritics/accents to ASCII equivalents (`á`->`a`, `é`->`e`, `í`->`i`, `ó`->`o`, `ú`->`u`, `ñ`->`n`).
3. Strip any non-alphanumeric character and replace it with a single underscore (`_`).
4. Prevent sequential underscores (e.g., `__` becomes `_`) and trim leading/trailing underscores.

---

### 12. Dependencias del proyecto (`requirements.txt`)

```
edge-tts
flask
mutagen
gunicorn
```

**Nota:** Se ha eliminado `pydub` (que requería FFmpeg externo) para compatibilidad con Pydroid. Los audios se generan por separado y la pausa se calcula programáticamente en el navegador.

---

### 13. Ejecución

```bash
# Modo servidor web (Flask - desarrollo)
python app.py
# Abrir en navegador: http://localhost:5000

# Modo servidor web (Gunicorn - producción/Docker)
gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 2 --threads 4 --timeout 120 app:app

# Modo línea de comandos (original)
python traducciones.py
```

En desarrollo, el servidor Flask se ejecuta en `http://0.0.0.0:5000` con modo debug y `threaded=True`.

---

### 14. Despliegue con Docker

El proyecto incluye un `Dockerfile` preparado para **Back4App**:

- Base: `python:3.11-slim`
- Puerto configurable via `$PORT` (Back4App asigna automáticamente)
- Gunicorn con 2 workers y 4 threads
- Variables de entorno: `PYTHONUNBUFFERED=1`, `FLASK_ENV=production`
- Directorios creados: `static/audio`, `csv`, `offline`

```bash
# Construir imagen
docker build -t inglesv5 .

# Ejecutar contenedor
docker run -p 8080:8080 inglesv5
```

---

### 15. Validaciones de seguridad

- Archivo CSV obligatorio y con extensión `.csv`.
- Carpeta de salida obligatoria; se crea automáticamente si no existe.
- Límite de subida: 16 MB (`MAX_CONTENT_LENGTH`).
- Manejo de errores por línea (fallo de TTS, archivo corrupto, etc.) sin detener el proceso completo.
- El endpoint `/servir_audio` normaliza la ruta y verifica que el archivo esté dentro del directorio permitido (protección contra path traversal).
- Solo se sirven archivos con extensión `.mp3`.

---

### 16. Compatibilidad con Pydroid

El proyecto es compatible con **Pydroid** (app Android) ya que:
- Se eliminó la dependencia de `pydub` (requería FFmpeg, no disponible en Pydroid).
- La pausa entre español e inglés se calcula programáticamente en el navegador.
- Solo se requiere `edge-tts`, `flask` y `mutagen` como dependencias Python.