# ============================================================
# Dockerfile para InglesV5 - Flask App en Back4App
# ============================================================
# Back4App asigna automáticamente el puerto via variable de entorno $PORT
# ============================================================

FROM python:3.11-slim

# ── Variables de entorno ────────────────────────────────────
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FLASK_APP=app.py \
    FLASK_ENV=production

# ── Instalar dependencias del sistema ───────────────────────
# RUN apt-get update && apt-get install -y --no-install-recommends \
#    build-essential \
#    && rm -rf /var/lib/apt/lists/*

# ── Crear directorio de trabajo ─────────────────────────────
WORKDIR /app

# ── Copiar requirements e instalar dependencias Python ──────
COPY requirements.txt .
# RUN pip install --no-cache-dir -r requirements.txt \
#     && pip install --no-cache-dir gunicorn
RUN pip install --no-cache-dir -r requirements.txt

# ── Copiar el código de la aplicación ───────────────────────
COPY . .

# ── Crear directorios necesarios ────────────────────────────
# RUN mkdir -p static/audio && \
#    mkdir -p csv && \
#    mkdir -p offline

# ── Puerto que Back4App usará (sobreescribible via $PORT) ───
EXPOSE 8080

# ── Comando de inicio (Gunicorn en producción) ──────────────
# Back4App asigna el puerto mediante la variable de entorno PORT
# CMD gunicorn --bind 0.0.0.0:${PORT:-8080} \
#              --workers 2 \
#              --threads 4 \
#              --timeout 120 \
#              --access-logfile - \
#              --error-logfile - \
#              app:app
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "8", "--timeout", "120", "app:app"]