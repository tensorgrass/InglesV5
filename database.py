"""
Módulo de base de datos SQLite.
Conexiones, inicialización y operaciones con temas/pares.
"""
import sqlite3
from flask import g


def get_db():
    """Obtiene una conexión a la base de datos (thread-safe)."""
    conn = sqlite3.connect(g.app.config['DATABASE'], check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode=WAL")  # Permite lecturas concurrentes
    return conn


def init_db(app):
    """Inicializa la base de datos creando las tablas si no existen."""
    conn = sqlite3.connect(app.config['DATABASE'], check_same_thread=False)
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


def crear_tema(app, nombre, descripcion=''):
    """Crea un nuevo tema y devuelve su ID."""
    conn = sqlite3.connect(app.config['DATABASE'], check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(
            "INSERT INTO themes (name, description) VALUES (?, ?)",
            (nombre, descripcion)
        )
        conn.commit()
        tema_id = cursor.lastrowid
        return tema_id, None
    except sqlite3.IntegrityError:
        cursor = conn.execute("SELECT id FROM themes WHERE name = ?", (nombre,))
        row = cursor.fetchone()
        if row and descripcion:
            conn.execute(
                "UPDATE themes SET description = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (descripcion, row['id'])
            )
            conn.commit()
        return row['id'], "Tema existente actualizado" if row else None
    finally:
        conn.close()


def guardar_pares_en_bd(app, tema_id, resultados):
    """Guarda los resultados de la generación en la base de datos."""
    conn = sqlite3.connect(app.config['DATABASE'], check_same_thread=False)
    try:
        for r in resultados:
            conn.execute(
                "INSERT INTO audio_pairs (theme_id, line_number, text_es, text_en, file_es, file_en, pause_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (tema_id, r['linea'], r['texto_es'], r['texto_en'],
                 r['archivo_es'], r['archivo_en'], r['pausa_ms'])
            )
        conn.commit()
    finally:
        conn.close()


def listar_temas_db(app):
    """Devuelve la lista de temas con metadatos."""
    conn = sqlite3.connect(app.config['DATABASE'], check_same_thread=False)
    conn.row_factory = sqlite3.Row
    temas = conn.execute("""
        SELECT t.*, COUNT(ap.id) as total_pares
        FROM themes t
        LEFT JOIN audio_pairs ap ON ap.theme_id = t.id
        GROUP BY t.id
        ORDER BY t.name ASC
    """).fetchall()
    conn.close()
    return temas


def obtener_tema_db(app, tema_id):
    """Devuelve un tema con sus pares de audio."""
    conn = sqlite3.connect(app.config['DATABASE'], check_same_thread=False)
    conn.row_factory = sqlite3.Row
    tema = conn.execute("SELECT * FROM themes WHERE id = ?", (tema_id,)).fetchone()
    pares = []
    if tema:
        pares = conn.execute(
            "SELECT * FROM audio_pairs WHERE theme_id = ? ORDER BY line_number ASC",
            (tema_id,)
        ).fetchall()
    conn.close()
    return tema, pares


def actualizar_tema_db(app, tema_id, nombre, descripcion):
    """Actualiza nombre y descripción de un tema."""
    conn = sqlite3.connect(app.config['DATABASE'], check_same_thread=False)
    try:
        conn.execute(
            "UPDATE themes SET name = ?, description = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (nombre, descripcion, tema_id)
        )
        conn.commit()
        return True, None
    except sqlite3.IntegrityError:
        return False, 'Ya existe un tema con ese nombre'
    finally:
        conn.close()


def eliminar_tema_db(app, tema_id):
    """Elimina un tema de la base de datos."""
    conn = sqlite3.connect(app.config['DATABASE'], check_same_thread=False)
    conn.row_factory = sqlite3.Row
    tema = conn.execute("SELECT * FROM themes WHERE id = ?", (tema_id,)).fetchone()
    if tema:
        conn.execute("DELETE FROM themes WHERE id = ?", (tema_id,))
        conn.commit()
    conn.close()
    return tema


def listar_temas_con_pares(app):
    """Lista temas que tienen al menos un par de audio."""
    conn = sqlite3.connect(app.config['DATABASE'], check_same_thread=False)
    conn.row_factory = sqlite3.Row
    temas = conn.execute("""
        SELECT t.*, COUNT(ap.id) as total_pares
        FROM themes t
        LEFT JOIN audio_pairs ap ON ap.theme_id = t.id
        GROUP BY t.id
        HAVING total_pares > 0
        ORDER BY t.name ASC
    """).fetchall()
    conn.close()
    return temas


def guardar_csv_file(app, tema_id, filename):
    """Guarda el registro de un archivo CSV subido."""
    conn = sqlite3.connect(app.config['DATABASE'], check_same_thread=False)
    conn.execute("INSERT INTO csv_files (theme_id, filename) VALUES (?, ?)",
                 (tema_id, filename))
    conn.execute("UPDATE themes SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (tema_id,))
    conn.commit()
    conn.close()


def obtener_pares_por_temas(app, tema_ids):
    """Obtiene pares de audio de múltiples temas."""
    conn = sqlite3.connect(app.config['DATABASE'], check_same_thread=False)
    conn.row_factory = sqlite3.Row
    placeholders = ','.join('?' * len(tema_ids))
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
    return pares