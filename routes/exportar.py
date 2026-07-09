"""
Rutas de exportación de temas.
Exporta audios + HTML offline a un directorio.
"""
import os
import json
import shutil
from flask import jsonify, request, render_template
from database import listar_temas_con_pares, obtener_tema_db
from audio_generator import limpiar_texto


def register(app):
    @app.route('/exportar')
    def exportar():
        """Página para exportar un tema a un directorio."""
        temas = listar_temas_con_pares(app)
        return render_template('exportar.html', temas=temas)

    @app.route('/api/exportar', methods=['POST'])
    def api_exportar():
        """
        Exporta un tema: copia los audios al directorio destino y genera un HTML
        que funciona offline con el mismo comportamiento que el reproductor.
        """
        data = request.get_json()
        tema_id = data.get('tema_id')
        destino = data.get('destino', '').strip()

        if not tema_id:
            return jsonify({'success': False, 'error': 'Debes especificar un tema.'}), 400
        if not destino:
            return jsonify({'success': False, 'error': 'Debes especificar el directorio de destino.'}), 400

        tema, pares = obtener_tema_db(app, tema_id)
        if not tema:
            return jsonify({'success': False, 'error': 'Tema no encontrado.'}), 404

        if not pares:
            return jsonify({'success': False, 'error': 'El tema no tiene pares de audio.'}), 400

        tema_dir = os.path.join(app.config['AUDIO_BASE'], limpiar_texto(tema['name']))
        if not os.path.isdir(tema_dir):
            return jsonify({'success': False, 'error': f'El directorio del tema no existe: {tema_dir}'}), 400

        # Crear directorio destino
        os.makedirs(destino, exist_ok=True)

        pares_exportados = []
        errores = []

        for p in pares:
            archivo_es = p['file_es']
            archivo_en = p['file_en']
            ruta_origen_es = os.path.join(tema_dir, archivo_es)
            ruta_origen_en = os.path.join(tema_dir, archivo_en)
            ruta_dest_es = os.path.join(destino, archivo_es)
            ruta_dest_en = os.path.join(destino, archivo_en)

            try:
                if os.path.isfile(ruta_origen_es):
                    shutil.copy2(ruta_origen_es, ruta_dest_es)
                if os.path.isfile(ruta_origen_en):
                    shutil.copy2(ruta_origen_en, ruta_dest_en)

                pares_exportados.append({
                    'linea': p['line_number'],
                    'texto_es': p['text_es'],
                    'texto_en': p['text_en'],
                    'archivo_es': archivo_es,
                    'archivo_en': archivo_en,
                    'pausa_ms': p['pause_ms']
                })
            except Exception as e:
                errores.append({
                    'linea': p['line_number'],
                    'texto': p['text_es'],
                    'error': str(e)
                })

        # Generar el HTML offline
        html_offline = _generar_html_offline(tema['name'], pares_exportados)
        html_path = os.path.join(destino, f"{limpiar_texto(tema['name'])}_player.html")
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_offline)

        response = {
            'success': True,
            'tema': tema['name'],
            'destino': destino,
            'total_exportados': len(pares_exportados),
            'errores': len(errores),
            'archivo_html': os.path.basename(html_path)
        }

        if errores:
            response['detalles_errores'] = errores

        return jsonify(response)


def _generar_html_offline(tema_nombre, pares):
    """
    Genera un HTML autónomo que funciona offline.
    Los audios se sirven desde rutas relativas (mismo directorio).
    """
    pares_json = json.dumps(pares, ensure_ascii=False, indent=2)

    html = f'''<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{tema_nombre} - Reproductor Offline</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacFontSystem, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh; color: #333; line-height: 1.6;
        }}
        .container {{ max-width: 800px; margin: 0 auto; padding: 2rem 1rem; }}
        header {{ text-align: center; margin-bottom: 2rem; color: white; }}
        header h1 {{ font-size: 2.5rem; margin-bottom: 0.5rem; text-shadow: 2px 2px 4px rgba(0,0,0,0.2); }}
        .subtitle {{ font-size: 1.1rem; opacity: 0.9; }}
        .card {{ background: white; border-radius: 12px; padding: 1.5rem; box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin-bottom: 1.5rem; }}
        .card h2 {{ margin-bottom: 1rem; color: #667eea; }}
        .file-list {{ max-height: 300px; overflow-y: auto; background: #f9f9f9; border-radius: 8px; padding: 0.5rem; margin-bottom: 1rem; }}
        .file-item {{ padding: 0.3rem 0.5rem; border-bottom: 1px solid #eee; font-size: 0.9rem; cursor: pointer; transition: background 0.15s; }}
        .file-item:last-child {{ border-bottom: none; }}
        .file-item:hover {{ background: #f5f5ff; }}
        .file-item.active {{ background: #e8e8ff; border-left: 4px solid #667eea; font-weight: 600; }}
        .pair-header {{ font-weight: 600; color: #667eea; padding: 0.5rem 0; font-size: 0.9rem; border-bottom: 1px solid #e0e0e0; margin-bottom: 0.3rem; }}
        .file-pair {{ display: flex; flex-wrap: wrap; align-items: center; gap: 0.3rem; }}
        .pair-num {{ font-weight: 600; color: #999; min-width: 1.5rem; }}
        .pair-es {{ color: #333; }}
        .pair-arrow {{ color: #aaa; font-size: 0.9rem; }}
        .pair-en {{ color: #333; }}
        .pair-pause {{ color: #667eea; font-size: 0.8rem; margin-left: auto; }}
        .player-controls {{ margin-top: 1rem; text-align: center; }}
        .btn-play {{ padding: 0.7rem 2rem; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border: none; border-radius: 8px; font-size: 1.1rem; font-weight: 600; cursor: pointer; transition: opacity 0.2s, transform 0.1s; }}
        .btn-play:hover {{ opacity: 0.9; }}
        .btn-play:active {{ transform: scale(0.98); }}
        .btn-play:disabled {{ opacity: 0.5; cursor: not-allowed; }}
        .progress-bar-container {{ width: 100%; height: 20px; background: #e0e0e0; border-radius: 10px; overflow: hidden; margin-bottom: 0.5rem; }}
        .progress-bar {{ height: 100%; width: 0%; background: linear-gradient(90deg, #667eea, #764ba2); border-radius: 10px; transition: width 0.3s ease; }}
        .time-display {{ text-align: center; font-size: 0.95rem; color: #666; margin-bottom: 0.5rem; font-family: monospace; }}
        .transport-controls {{ display: flex; justify-content: center; align-items: center; gap: 1rem; margin: 1rem 0; }}
        .btn-transport {{ width: 50px; height: 50px; border: none; border-radius: 50%; background: #f0f0f0; font-size: 1.3rem; cursor: pointer; transition: background 0.2s, transform 0.1s; display: inline-flex; align-items: center; justify-content: center; }}
        .btn-transport:hover {{ background: #e0e0e0; }}
        .btn-transport:active {{ transform: scale(0.92); }}
        .btn-large {{ width: 60px; height: 60px; font-size: 1.6rem; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; }}
        .btn-large:hover {{ opacity: 0.9; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }}
        .phase-indicator {{ text-align: center; margin-bottom: 1rem; padding: 0.5rem; background: #f9f9f9; border-radius: 8px; min-height: 40px; display: flex; align-items: center; justify-content: center; }}
        .phase-phase {{ font-size: 1.1rem; font-weight: 600; color: #555; animation: fadeIn 0.3s ease; }}
        .phase-done {{ color: #28a745; }}
        @keyframes fadeIn {{ from {{ opacity: 0; transform: translateY(-5px); }} to {{ opacity: 1; transform: translateY(0); }} }}
        .playlist-info {{ text-align: center; font-size: 0.9rem; color: #888; margin-top: 0.5rem; }}
        .hidden {{ display: none; }}
        .empty-msg {{ text-align: center; color: #999; padding: 1rem; }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🎧 {tema_nombre}</h1>
            <p class="subtitle">Reproductor offline - Español → Inglés con pausa inteligente</p>
        </header>
        <div id="fileListArea" class="card">
            <h2>Lista de reproducción</h2>
            <div id="fileListContainer" class="file-list"></div>
            <div class="player-controls">
                <button id="btnPlayAll" class="btn-play">▶️ Reproducir todo</button>
            </div>
        </div>
        <div id="playerArea" class="card hidden">
            <h2 id="nowPlaying">Reproduciendo: —</h2>
            <div id="phaseIndicator" class="phase-indicator">
                <span id="phaseEs" class="phase-phase">🇪🇸 Escuchando español...</span>
                <span id="phasePause" class="phase-phase hidden">⏸️ Pausa de <span id="pauseCountdown">0</span>ms...</span>
                <span id="phaseEn" class="phase-phase hidden">🇬🇧 Repitiendo en inglés...</span>
                <span id="phaseDone" class="phase-phase phase-done hidden">✅ ¡Completado!</span>
            </div>
            <div class="progress-bar-container">
                <div class="progress-bar" id="playbackProgress"></div>
            </div>
            <div class="time-display">
                <span id="currentTime">00:00</span> / <span id="totalTime">00:00</span>
            </div>
            <div class="transport-controls">
                <button id="btnPrev" class="btn-transport" title="Anterior">⏮️</button>
                <button id="btnPlayPause" class="btn-transport btn-large" title="Reproducir/Pausar">▶️</button>
                <button id="btnStop" class="btn-transport" title="Parar">⏹️</button>
                <button id="btnNext" class="btn-transport" title="Siguiente">⏭️</button>
            </div>
            <p id="playlistInfo" class="playlist-info">Par 0 de 0</p>
        </div>
    </div>
    <script>
        const pares = {pares_json};
        let currentIndex = -1, isPlaying = false, isPaused = false, phase = 'stopped', audioElement = null, pauseTimeout = null, audioErrorHandler = null;
        const fileListContainer = document.getElementById('fileListContainer'), playerArea = document.getElementById('playerArea');
        const btnPlayAll = document.getElementById('btnPlayAll'), nowPlaying = document.getElementById('nowPlaying');
        const phaseEs = document.getElementById('phaseEs'), phasePause = document.getElementById('phasePause');
        const phaseEn = document.getElementById('phaseEn'), phaseDone = document.getElementById('phaseDone');
        const pauseCountdown = document.getElementById('pauseCountdown'), playbackProgress = document.getElementById('playbackProgress');
        const currentTimeSpan = document.getElementById('currentTime'), totalTimeSpan = document.getElementById('totalTime');
        const btnPrev = document.getElementById('btnPrev'), btnPlayPause = document.getElementById('btnPlayPause');
        const btnStop = document.getElementById('btnStop'), btnNext = document.getElementById('btnNext'), playlistInfo = document.getElementById('playlistInfo');

        function formatTime(s) {{ return isNaN(s)||s<0?'00:00':String(Math.floor(s/60)).padStart(2,'0')+':'+String(Math.floor(s%60)).padStart(2,'0'); }}
        function escapeHtml(t) {{ const d=document.createElement('div'); d.textContent=t; return d.innerHTML; }}
        function ocultarFases() {{ ['phaseEs','phasePause','phaseEn','phaseDone'].forEach(id=>document.getElementById(id).classList.add('hidden')); }}
        function mostrarFase(f) {{ ocultarFases(); document.getElementById('phase'+f.charAt(0).toUpperCase()+f.slice(1)).classList.remove('hidden'); phase=f; }}
        function parActual() {{ return currentIndex>=0&currentIndex<pares.length?pares[currentIndex]:null; }}

        function mostrarLista() {{
            let html='';
            if(pares.length>0) {{
                html+='<div class="pair-header">Pares Español ↔ Inglés:</div>';
                pares.forEach((p,i)=>{{
                    html+='<div class="file-item file-pair" data-index="'+i+'"><span class="pair-num">'+(i+1)+'.</span><span class="pair-es">🇪🇸 '+escapeHtml(p.texto_es)+' <small>('+p.archivo_es+')</small></span><span class="pair-arrow">→</span><span class="pair-en">🇬🇧 '+escapeHtml(p.texto_en)+' <small>('+p.archivo_en+')</small></span><span class="pair-pause">⏸️ '+p.pausa_ms+'ms</span></div>';
                }});
            }}
            if(!html) {{ html='<p class="empty-msg">No hay pares para reproducir.</p>'; btnPlayAll.disabled=true; }}
            fileListContainer.innerHTML=html;
            fileListContainer.querySelectorAll('.file-pair').forEach(el=>el.addEventListener('click',function(){{ reproducirParDesde(parseInt(this.dataset.index)); }}));
        }}

        function reproducirParDesde(idx) {{
            if(idx<0||idx>=pares.length) return;
            currentIndex=idx; limpiarAudio();
            if(pauseTimeout) {{ clearInterval(pauseTimeout); pauseTimeout=null; }}
            playerArea.classList.remove('hidden'); reproducirFaseEs();
        }}

        function reproducirFaseEs() {{
            const p=parActual();
            if(!p||!p.archivo_es) {{ if(p&&p.archivo_en) {{ reproducirFaseEn(); return; }} avanzar(); return; }}
            mostrarFase('es'); prepararAudio(p.archivo_es,function(){{ mostrarFase('pause'); iniciarPausa(); }});
            nowPlaying.textContent='🇪🇸 '+p.texto_es; playlistInfo.textContent='Par '+(currentIndex+1)+' de '+pares.length; actualizarResaltado();
        }}

        function reproducirFaseEn() {{
            const p=parActual();
            if(!p||!p.archivo_en) {{ avanzar(); return; }}
            mostrarFase('en'); prepararAudio(p.archivo_en,function(){{ mostrarFase('done'); setTimeout(function(){{ avanzar(); }},800); }});
            nowPlaying.textContent='🇬🇧 '+p.texto_en;
        }}

        function prepararAudio(url,onEnded) {{
            limpiarAudio(); audioElement=new Audio(url); audioElement.preload='auto';
            audioElement.addEventListener('loadedmetadata',function(){{ totalTimeSpan.textContent=formatTime(audioElement.duration); playbackProgress.style.width='0%'; currentTimeSpan.textContent='00:00'; }});
            audioElement.addEventListener('timeupdate',function(){{ if(audioElement.duration){{ const pct=(audioElement.currentTime/audioElement.duration)*100; playbackProgress.style.width=pct+'%'; currentTimeSpan.textContent=formatTime(audioElement.currentTime); }} }});
            audioElement.addEventListener('ended',function(){{ if(onEnded) onEnded(); }});
            audioErrorHandler=function(){{ console.error('Error audio'); if(onEnded) onEnded(); }}; audioElement.addEventListener('error',audioErrorHandler);
            audioElement.play().then(()=>{{ isPlaying=true; isPaused=false; btnPlayPause.textContent='⏸️'; }}).catch(function(err){{ console.error(err); if(onEnded) onEnded(); }});
        }}

        function iniciarPausa() {{
            const p=parActual(); if(!p) return;
            const ms=p.pausa_ms; pauseCountdown.textContent=ms;
            const start=Date.now();
            pauseTimeout=setInterval(function(){{
                const e=Date.now()-start, r=Math.max(0,ms-e);
                pauseCountdown.textContent=r; playbackProgress.style.width=Math.min((e/ms)*100,100)+'%'; currentTimeSpan.textContent=formatTime(e/1000);
                if(r<=0){{ clearInterval(pauseTimeout); pauseTimeout=null; reproducirFaseEn(); }}
            }},50);
            totalTimeSpan.textContent=formatTime(ms/1000);
        }}

        function avanzar() {{
            if(currentIndex<pares.length-1) {{ reproducirParDesde(currentIndex+1); }}
            else {{
                isPlaying=false; isPaused=false; btnPlayPause.textContent='▶️';
                nowPlaying.textContent='🎉 Reproducción finalizada'; mostrarFase('done');
                document.getElementById('phaseDone').textContent='✅ ¡Lista completa!';
                playbackProgress.style.width='100%'; currentTimeSpan.textContent='00:00'; totalTimeSpan.textContent='00:00'; actualizarResaltado();
            }}
        }}

        function limpiarAudio() {{
            if(audioElement) {{
                if(audioErrorHandler) audioElement.removeEventListener('error',audioErrorHandler);
                audioElement.pause(); audioElement.src=''; audioElement.load(); audioElement=null;
            }}
        }}

        function detener() {{ limpiarAudio(); isPlaying=false; isPaused=false; btnPlayPause.textContent='▶️'; playbackProgress.style.width='0%'; currentTimeSpan.textContent='00:00'; totalTimeSpan.textContent='00:00'; }}

        function actualizarResaltado() {{
            fileListContainer.querySelectorAll('.file-item').forEach(el=>{{ el.classList.remove('active'); if(parseInt(el.dataset.index)===currentIndex){{ el.classList.add('active'); el.scrollIntoView({{block:'nearest',behavior:'smooth'}}); }} }});
        }}

        btnPlayAll.addEventListener('click',function(){{ if(pares.length>0) reproducirParDesde(0); }});
        btnPlayPause.addEventListener('click',function(){{
            if(phase==='pause') {{
                if(isPaused) {{
                    isPaused=false; btnPlayPause.textContent='⏸️'; const p=parActual();
                    if(p&&pauseTimeout) {{
                        const remaining=parseInt(pauseCountdown.textContent), start=Date.now();
                        pauseTimeout=setInterval(function(){{ const e=Date.now()-start, r=Math.max(0,remaining-e); pauseCountdown.textContent=r; playbackProgress.style.width=Math.min(((remaining-r)/p.pausa_ms)*100,100)+'%'; if(r<=0){{ clearInterval(pauseTimeout); pauseTimeout=null; reproducirFaseEn(); }} }},50);
                    }}
                }} else {{ isPaused=true; btnPlayPause.textContent='▶️'; if(pauseTimeout){{ clearInterval(pauseTimeout); pauseTimeout=null; }} }}
                return;
            }}
            if(!audioElement) return;
            if(isPlaying&&!isPaused) {{ audioElement.pause(); isPaused=true; btnPlayPause.textContent='▶️'; }}
            else if(isPaused) {{ audioElement.play().then(()=>{{ isPaused=false; isPlaying=true; btnPlayPause.textContent='⏸️'; }}).catch(console.error); }}
        }});
        btnStop.addEventListener('click',function(){{ if(pauseTimeout){{ clearInterval(pauseTimeout); pauseTimeout=null; }} detener(); ocultarFases(); phase='stopped'; nowPlaying.textContent='Reproducción detenida'; playlistInfo.textContent=''; phaseEs.textContent='🇪🇸 Escuchando español...'; actualizarResaltado(); }});
        btnNext.addEventListener('click',function(){{ if(pauseTimeout){{ clearInterval(pauseTimeout); pauseTimeout=null; }} limpiarAudio(); avanzar(); }});
        btnPrev.addEventListener('click',function(){{ if(currentIndex>0){{ if(pauseTimeout){{ clearInterval(pauseTimeout); pauseTimeout=null; }} limpiarAudio(); reproducirParDesde(currentIndex-1); }} }});
        mostrarLista();
    </script>
</body>
</html>'''
    return html