> **⚠️ Mantenimiento:** Este archivo debe actualizarse siempre que se añadan nuevas funcionalidades, cambios arquitectónicos o decisiones técnicas importantes al proyecto. Mantén esta documentación viva y sincronizada con el código.

---

## Arquitectura del Proyecto

```
InglesV5/
├── app.py                   → Aplicación Flask (punto de entrada web)
├── traducciones.py          → Script original de línea de comandos (conservado)
├── traducciones.csv         → CSV de ejemplo con frases español/inglés
├── database.db              → Base de datos SQLite (temas, pares de audio, CSVs)
├── templates/
│   ├── index.html           → Página principal con menú de navegación
│   ├── generar.html         → Formulario para subir CSV y generar audios por tema
│   ├── reproducir.html      → Reproductor secuencial ES → pausa → EN
│   └── temas.html           → Gestión de temas (CRUD)
├── static/
│   ├── style.css            → Estilos CSS con diseño responsive
│   └── audio/               → Directorio con subcarpetas por tema
└── agents.md                → Documentación del proyecto
```

### 1. Migración a Flask (Web GUI)

El proyecto ahora cuenta con una interfaz web basada en **Flask** que expone las mismas funcionalidades del script original a través de un navegador.

#### 1.1 Rutas de la aplicación

| Ruta | Método | Descripción |
|------|--------|-------------|
| `/` | GET | Página principal con menú y explicación de uso |
| `/generar` | GET | Formulario para subir CSV y especificar carpeta de salida |
| `/procesar` | POST | Endpoint que recibe el CSV + carpeta de salida y genera los audios por separado |
| `/descargar/<filename>` | GET | Descarga un archivo de audio individual desde la carpeta de salida |
| `/reproducir` | GET | Reproductor de audios con lista de reproducción secuencial |
| `/listar_audios` | POST | Escanea un directorio, agrupa los MP3 en pares ES/EN y devuelve la info |
| `/servir_audio` | GET | Sirve un archivo MP3 individual para reproducción en el navegador |

#### 1.2 Flujo de trabajo (generación)

1. El usuario accede a `http://localhost:5000/` en el navegador.
2. Hace clic en **"Generar Audios"** → formulario en `/generar`.
3. Adjunta un archivo CSV y escribe la ruta de la carpeta de salida.
4. El formulario envía los datos vía `POST` a `/procesar` usando `FormData`.
5. El endpoint `/procesar` valida el archivo y la carpeta, y ejecuta la generación.
6. Para cada línea del CSV, genera **dos archivos MP3 separados**:
   - `{PREFIJO}_{LINEA}_{TEXTO_SANITIZADO}_es.mp3` (voz española)
   - `{PREFIJO}_{LINEA}_{TEXTO_SANITIZADO}_en.mp3` (voz inglesa)
7. Devuelve un JSON con `success`, `total`, `resultados` (con ambos archivos) y `errores`.

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

#### 2.2 `calcular_pausa_estimada(texto_en)` y `calcular_pausa_por_duracion(duracion_segundos)`
Reemplazan a **The Silence Gap Formula** que requería `pydub`. Ahora se usan dos métodos para calcular la pausa:
- **`calcular_pausa_estimada`**: Heurística basada en número de palabras (~150ms por palabra + 300ms base, mínimo 800ms). Se usa durante la generación del CSV.
- **`calcular_pausa_por_duracion`**: Aproximación del 70% de la duración del audio en inglés. Se usa en el reproductor cuando se escanea el directorio.

#### 2.3 `generar_audios_desde_csv(csv_path, output_dir, progreso_callback=None)`
Función asíncrona que:
- Lee el CSV fila por fila.
- Genera audio TTS para español (`es-ES-AlvaroNeural`) e inglés (`en-US-GuyNeural`) usando `edge-tts`.
- Guarda cada audio como archivo separado (ES y EN independientes).
- Exporta cada resultado como archivo MP3 individual.
- Acepta un callback opcional para notificar progreso en tiempo real.
- Reporta errores por línea sin interrumpir el procesamiento.

---

### 3. Pausa programática en el navegador

Anteriormente, los audios se concatenaban con `pydub` (requería FFmpeg, incompatible con Pydroid). Ahora:

- **Los audios se generan por separado**: un archivo `_es.mp3` y otro `_en.mp3` por cada línea del CSV.
- **La pausa se genera programáticamente en el navegador**: al reproducir, el reproductor calcula una pausa basada en la duración del audio en inglés (~70% de su duración) o en la longitud del texto (~150ms por palabra).
- **Flujo de reproducción secuencial**:
  1. 🇪🇸 **Español** → se reproduce el audio en español.
  2. ⏸️ **Pausa** → se muestra un contador regresivo con la pausa calculada.
  3. 🇬🇧 **Inglés** → se reproduce el audio en inglés.
  4. ✅ **Completado** → se avanza automáticamente al siguiente par.

---

### 4. Output File Naming Convention

Files must be exported individually using a strict sanitized pattern:
`{PREFIJO}_{Numero_Linea}_{Texto_Columna_1_Sanitizado}_es.mp3`
`{PREFIJO}_{Numero_Linea}_{Texto_Columna_1_Sanitizado}_en.mp3`

### Sanitization Rules (`limpiar_texto`):
1. Convert all characters to lowercase.
2. Flatten common Spanish diacritics/accents to ASCII equivalents (`á`->`a`, `é`->`e`, `í`->`i`, `ó`->`o`, `ú`->`u`, `ñ`->`n`).
3. Strip any non-alphanumeric character and replace it with a single underscore (`_`).
4. Prevent sequential underscores (e.g., `__` becomes `_`) and trim leading/trailing underscores.

---

### 5. Dependencias del proyecto

```
pip install edge-tts flask mutagen
```

**Nota:** Se ha eliminado `pydub` (que requería FFmpeg externo) para compatibilidad con Pydroid. Ahora los audios se generan por separado y la pausa se calcula programáticamente en el navegador.

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
2. La aplicación escanea el directorio, **agrupa los archivos en pares** ES/EN usando el patrón de nombres (`_es.mp3` / `_en.mp3`), y ordena alfabéticamente.
3. Se muestra una lista de reproducción con todos los pares encontrados y su duración.
4. El usuario puede:
   - **Reproducir todo** desde el principio.
   - **Hacer clic** en cualquier par de la lista para empezar desde ahí.
   - Usar los controles de transporte: **Anterior (⏮️)**, **Reproducir/Pausar (▶️/⏸️)**, **Parar (⏹️)**, **Siguiente (⏭️)**.
5. Al finalizar cada fase (ES → pausa → EN), el reproductor avanza automáticamente al siguiente par.
6. Una barra de progreso muestra el avance de la reproducción, y el par activo se resalta en la lista.

#### 8.2 Indicador de fase

El reproductor muestra un indicador visual de la fase actual:
- **🇪🇸 Escuchando español...** → reproduciendo audio en español.
- **⏸️ Pausa de Xms...** → contador regresivo de la pausa programática.
- **🇬🇧 Repitiendo en inglés...** → reproduciendo audio en inglés.
- **✅ ¡Completado!** → par finalizado.

#### 8.3 Nuevas rutas

| Ruta | Método | Descripción |
|------|--------|-------------|
| `/reproducir` | GET | Página del reproductor de audios |
| `/listar_audios` | POST | Escanea un directorio, agrupa en pares `_es.mp3`/`_en.mp3`, devuelve nombre + duración + pausa calculada |
| `/servir_audio` | GET | Sirve un archivo MP3 individual para el reproductor del navegador (con validación anti path traversal) |

#### 8.4 Controles del reproductor

El frontend (`templates/reproducir.html`) gestiona todo el estado del reproductor en JavaScript:
- `pares[]`: array con los pares ES/EN obtenidos del servidor.
- `sueltos[]`: archivos MP3 que no siguen el patrón de pares.
- `currentIndex`: índice del elemento actual en la reproducción.
- `phase`: estado actual (`stopped`, `es`, `pause`, `en`, `done`).
- `audioElement`: objeto `Audio` de HTML5 para la reproducción.
- La pausa entre ES y EN se gestiona con `setInterval` que actualiza un contador regresivo.

#### 8.5 Validaciones de seguridad

- El endpoint `/listar_audios` verifica que el directorio exista antes de escanear.
- El endpoint `/servir_audio` normaliza la ruta y comprueba que el archivo solicitado esté dentro del directorio permitido (protección contra path traversal).
- Solo se sirven archivos con extensión `.mp3`.

---

### 9. Compatibilidad con Pydroid

A partir de esta versión, el proyecto es compatible con **Pydroid** (app Android) ya que:
- Se eliminó la dependencia de `pydub` (requería FFmpeg, no disponible en Pydroid).
- La pausa entre español e inglés se calcula programáticamente en el navegador.
- Solo se requiere `edge-tts`, `flask` y `mutagen` como dependencias Python.