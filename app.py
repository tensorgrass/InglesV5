"""
InglesV5 - Aplicación Flask para generación y reproducción de audios bilingües.
Punto de entrada principal. Las rutas están organizadas en módulos separados.
"""
import os
import sys
import tempfile
from flask import Flask

# ── Configuración ──────────────────────────────
from config import Config, PREFIJO

app = Flask(__name__)
app.config.from_object(Config)
app.config['UPLOAD_FOLDER'] = tempfile.gettempdir()
app.config['AUDIO_BASE'] = Config.get_audio_base(app.root_path)
app.config['DATABASE'] = Config.get_database(app.root_path)

# ── Inicializar base de datos ─────────────────
from database import init_db, get_db
init_db(app)

# ── Inicializar sistema de background tasks ───
from background import init_background
init_background(max_workers=app.config.get('MAX_WORKERS', 3))

# ── Registrar rutas (cada módulo registra sus endpoints) ──
from routes import main, temas, generar, reproductor, exportar, descargas

main.register(app)
temas.register(app)
generar.register(app)
reproductor.register(app)
exportar.register(app)
descargas.register(app)


if __name__ == '__main__':
    # Asegurar que existe el directorio base de audio
    os.makedirs(app.config['AUDIO_BASE'], exist_ok=True)
    # Usar el puerto asignado por Back4App ($PORT) o 5000 por defecto
    port = int(os.environ.get('PORT', 5000))
    # threaded=True permite manejar múltiples peticiones concurrentes
    app.run(debug=True, host='0.0.0.0', port=port, threaded=True)