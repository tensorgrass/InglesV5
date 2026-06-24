> **⚠️ Mantenimiento:** Este archivo debe actualizarse siempre que se añadan nuevas funcionalidades, cambios arquitectónicos o decisiones técnicas importantes al proyecto. Mantén esta documentación viva y sincronizada con el código.

### The Silence Gap Formula
Initially, using the absolute duration of the English audio introduced an over-extended gap due to natural audio padding added by TTS engines.
- **Solution implemented:** `pydub.silence.detect_nonsilent`.
- **Mechanism:** The script measures the net speech duration of the English clip by setting a noise threshold (default: `-50 dBFS`). It identifies the exact millisecond where active pronunciation starts and ends. The resulting gap duration equals this *net vocal activity time*, creating an optimal active-recall response window.

## 4. Output File Naming Convention
Files must be exported individually using a strict sanitized pattern:
`{PREFIJO}_{Numero_Linea}_{Texto_Columna_1_Sanitizado}.mp3`

### Sanitization Rules (`limpiar_texto`):
1. Convert all characters to lowercase.
2. Flatten common Spanish diacritics/accents to ASCII equivalents (`á`->`a`, `é`->`e`, `í`->`i`, `ó`->`o`, `ú`->`u`, `ñ`->`n`).
3. Strip any non-alphanumeric character and replace it with a single underscore (`_`).
4. Prevent sequential underscores (e.g., `__` becomes `_`) and trim leading/trailing underscores.

---

## 5. Reference Code Implementation