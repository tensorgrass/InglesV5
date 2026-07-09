"""
Rutas de descarga de frases en CSV.
Seleccionar temas y descargar frases.
"""
import csv
import io
from datetime import datetime
from flask import jsonify, request, render_template, Response
from database import obtener_pares_por_temas


def register(app):
    @app.route('/descargar-frases')
    def descargar_frases():
        """Página para seleccionar temas y descargar frases en CSV."""
        return render_template('descargar_frases.html')

    @app.route('/api/descargar-frases', methods=['POST'])
    def api_descargar_frases():
        """
        Recibe un array de IDs de temas y devuelve un CSV con todas las frases.
        """
        data = request.get_json()
        tema_ids = data.get('tema_ids', [])

        if not tema_ids or not isinstance(tema_ids, list):
            return jsonify({'error': 'Debes especificar al menos un tema.'}), 400

        pares = obtener_pares_por_temas(app, tema_ids)

        if not pares:
            return jsonify({'error': 'Los temas seleccionados no tienen frases.'}), 404

        # Generar CSV en memoria
        output = io.StringIO()
        output.write('\ufeff')  # BOM para Excel (UTF-8)
        writer = csv.writer(output)
        writer.writerow(['Tema', 'Línea', 'Español', 'Inglés'])

        for p in pares:
            writer.writerow([p['tema_nombre'], p['line_number'], p['text_es'], p['text_en']])

        csv_content = output.getvalue()
        output.close()

        return Response(
            csv_content,
            mimetype='text/csv; charset=utf-8',
            headers={
                'Content-Disposition': f'attachment; filename=frases_{datetime.now().strftime("%Y-%m-%d_%H-%M")}.csv',
                'Content-Type': 'text/csv; charset=utf-8'
            }
        )