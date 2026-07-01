import sqlite3; from app import app, get_db, init_db; init_db(); conn = get_db(); tables = conn.execute('select name from sqlite_master where type=\
table\').fetchall(); print('Tables:', [t[0] for t in tables]); conn.close(); print('OK')
