"""
Configuración centralizada de la aplicación Flask.
"""
import os
import tempfile

PREFIJO = "audio"


class Config:
    """Configuración de la aplicación."""
    SECRET_KEY = os.environ.get('SECRET_KEY', 'inglesv5-dev-key')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB max upload
    UPLOAD_FOLDER = tempfile.gettempdir()
    MAX_WORKERS = 3  # Hilos concurrentes para generación de audio

    @staticmethod
    def get_audio_base(app_root_path):
        return os.path.join(app_root_path, 'static', 'audio')

    @staticmethod
    def get_database(app_root_path):
        return os.path.join(app_root_path, 'database.db')