#!/usr/bin/env python3
"""
web_server.py - Flask web server for AI Subtitle Translator
Enabled/disabled via config.ini: [web] enabled = true/false
"""
import os
import uuid
import threading
import logging
import tempfile
from pathlib import Path
from flask import Flask, request, jsonify, send_file, render_template_string
from modules.GoogleAIAPIClient import GoogleAIAPIClient
from modules.Config import Config
from modules.Translation import Translation
from modules.VideoSubtitleExtractor import VideoSubtitleExtractor

logger = logging.getLogger(__name__)

app = Flask(__name__)

# In-memory job store: job_id -> { status, progress, message, result_path, error }
jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()

# Loaded once at startup
_google_api_client: GoogleAIAPIClient = None
_config: Config = None
_output_dir: str = None


def init_server(config: Config, output_dir: str):
    global _google_api_client, _config, _output_dir
    _config = config
    _output_dir = output_dir
    os.makedirs(output_dir, exist_ok=True)
    _google_api_client = GoogleAIAPIClient(
        api_key=config.google_ai_api_key,
        model_name=config.google_ai_model_name,
    )


def _update_job(job_id: str, **kwargs):
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id].update(kwargs)


def _process_file(job_id: str, file_path: str, translate_to_language: str, original_name: str):
    """Runs in a background thread. Processes one file and updates job state."""
    try:
        lower = original_name.lower()
        base_name = Path(original_name).stem
        output_srt = os.path.join(_output_dir, f"{base_name}.{translate_to_language}.srt")

        if lower.endswith(".srt"):
            # --- SRT path ---
            _update_job(job_id, status="translating", progress=10,
                        message="Reading SRT file…")

            # Count chunks for progress
            with open(file_path, "r", encoding="utf-8") as f:
                srt_text = f.read()
            chunks = Translation.split_srt_into_chunks(srt_text, split_at=100)
            total_chunks = len(chunks)

            _update_job(job_id, message=f"Translating {total_chunks} chunk(s)…", progress=20)

            # Monkey-patch to get per-chunk progress
            _translate_with_progress(
                job_id=job_id,
                input_path=file_path,
                output_path=output_srt,
                translate_to_language=translate_to_language,
                total_chunks=total_chunks,
            )

        elif lower.endswith((".mp4", ".mkv")):
            # --- Video path ---
            _update_job(job_id, status="extracting", progress=5,
                        message="Extracting subtitles from video…")

            extractor = VideoSubtitleExtractor(file_path)
            extracted_path = extractor.extract_subtitles()

            if extracted_path is None:
                _update_job(job_id, status="error", progress=0,
                            message="No subtitles found in video file.")
                return

            eng_srt_path = file_path + ".eng.srt"

            if extracted_path.suffix.lower() == ".sup":
                _update_job(job_id, status="converting", progress=30,
                            message="Converting PGS/SUP subtitles to SRT via OCR…")
                from modules.SupToSrtConverter.SupToSrtConverter import SupToSrtConverter
                converter = SupToSrtConverter(str(extracted_path), eng_srt_path)
                converter.convert()
                if _config.delete_pgs_files:
                    os.remove(str(extracted_path))
            else:
                os.rename(str(extracted_path), eng_srt_path)

            _update_job(job_id, status="translating", progress=50,
                        message="Subtitles extracted. Starting translation…")

            with open(eng_srt_path, "r", encoding="utf-8") as f:
                srt_text = f.read()
            chunks = Translation.split_srt_into_chunks(srt_text, split_at=100)
            total_chunks = len(chunks)

            _translate_with_progress(
                job_id=job_id,
                input_path=eng_srt_path,
                output_path=output_srt,
                translate_to_language=translate_to_language,
                total_chunks=total_chunks,
                progress_start=50,
            )
        else:
            _update_job(job_id, status="error", message="Unsupported file type.")
            return

        _update_job(job_id,
                    status="done",
                    progress=100,
                    message="Translation complete!",
                    result_path=output_srt,
                    result_filename=os.path.basename(output_srt))

    except Exception as e:
        logger.exception("Job %s failed", job_id)
        _update_job(job_id, status="error", progress=0, message=f"Error: {e}")
    finally:
        # Clean up temp upload
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass


def _translate_with_progress(job_id, input_path, output_path, translate_to_language,
                              total_chunks, progress_start=20):
    """Translates an SRT, emitting progress updates per chunk."""
    with open(input_path, "r", encoding="utf-8") as f:
        english_srt_text = f.read()

    chunks = Translation.split_srt_into_chunks(english_srt_text, split_at=100)
    translated_chunks = []
    progress_range = 100 - progress_start - 5  # leave 5% for final write

    for i, chunk in enumerate(chunks):
        pct = int(progress_start + (i / total_chunks) * progress_range)
        _update_job(job_id,
                    progress=pct,
                    message=f"Translating chunk {i + 1} of {total_chunks}…")

        prompt = (
            f"Please translate the entirety of the following SRT subtitles from English to {translate_to_language}. "
            "Preserve the same time stamps, line numbering, and overall SRT structure. "
            "Output only the translated SRT file contents, no additional text.\n\n"
            f"{chunk}"
        )
        translated_chunk = _google_api_client.send_prompt(prompt)
        translated_chunks.append(translated_chunk)

    _update_job(job_id, progress=95, message="Writing output file…")
    translated_text = "\n\n".join(translated_chunks)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(translated_text)


# ---------------------------------------------------------------------------
# HTML template (single-file SPA)
# ---------------------------------------------------------------------------
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>AI Subtitle Translator</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;800&family=DM+Mono:wght@300;400;500&display=swap" rel="stylesheet"/>
<style>
  :root {
    --bg: #0a0a0f;
    --surface: #111118;
    --border: #1e1e2e;
    --accent: #7c6af7;
    --accent2: #e05fb0;
    --text: #e8e8f0;
    --muted: #5a5a7a;
    --success: #4ade80;
    --error: #f87171;
    --warn: #fbbf24;
    --radius: 10px;
    --font-head: 'Syne', sans-serif;
    --font-mono: 'DM Mono', monospace;
  }
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: var(--font-mono);
    font-size: 14px;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 40px 20px 80px;
  }
  /* Noise overlay */
  body::before {
    content: '';
    position: fixed; inset: 0;
    background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.04'/%3E%3C/svg%3E");
    pointer-events: none;
    z-index: 0;
  }
  .container { position: relative; z-index: 1; width: 100%; max-width: 760px; }

  header { margin-bottom: 48px; text-align: left; }
  header h1 {
    font-family: var(--font-head);
    font-size: clamp(28px, 5vw, 44px);
    font-weight: 800;
    letter-spacing: -1px;
    background: linear-gradient(120deg, var(--accent) 0%, var(--accent2) 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    line-height: 1.1;
  }
  header p { color: var(--muted); margin-top: 8px; font-size: 13px; }

  /* Controls row */
  .controls {
    display: flex;
    align-items: center;
    gap: 16px;
    margin-bottom: 24px;
    flex-wrap: wrap;
  }
  label.lang-label { color: var(--muted); font-size: 12px; letter-spacing: .08em; text-transform: uppercase; }
  select#langSelect {
    background: var(--surface);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 8px 14px;
    border-radius: var(--radius);
    font-family: var(--font-mono);
    font-size: 13px;
    cursor: pointer;
    outline: none;
    transition: border-color .2s;
  }
  select#langSelect:focus { border-color: var(--accent); }

  /* Drop zone */
  .dropzone {
    border: 2px dashed var(--border);
    border-radius: var(--radius);
    padding: 40px 24px;
    text-align: center;
    cursor: pointer;
    transition: border-color .2s, background .2s;
    position: relative;
    margin-bottom: 20px;
  }
  .dropzone.drag-over { border-color: var(--accent); background: rgba(124,106,247,.06); }
  .dropzone input[type=file] { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
  .dropzone .drop-icon {
    font-size: 36px;
    margin-bottom: 12px;
    display: block;
    filter: grayscale(1) opacity(.5);
    transition: filter .2s;
  }
  .dropzone:hover .drop-icon, .dropzone.drag-over .drop-icon { filter: none; }
  .dropzone p { color: var(--muted); font-size: 13px; }
  .dropzone strong { color: var(--text); }
  .dropzone small { display: block; margin-top: 6px; font-size: 11px; color: var(--muted); }

  /* File queue */
  #fileQueue { margin-bottom: 20px; display: flex; flex-direction: column; gap: 8px; }
  .file-item {
    display: flex;
    align-items: center;
    gap: 10px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 10px 14px;
    animation: slideIn .15s ease;
  }
  @keyframes slideIn { from { opacity: 0; transform: translateY(-6px); } to { opacity: 1; transform: none; } }
  .file-item .file-icon { font-size: 18px; flex-shrink: 0; }
  .file-item .file-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
  .file-item .file-size { color: var(--muted); font-size: 11px; flex-shrink: 0; }
  .file-item .remove-btn {
    background: none; border: none; color: var(--muted);
    cursor: pointer; font-size: 16px; padding: 0 4px; line-height: 1;
    transition: color .15s;
  }
  .file-item .remove-btn:hover { color: var(--error); }

  /* Translate button */
  #translateBtn {
    width: 100%;
    padding: 14px;
    border: none;
    border-radius: var(--radius);
    background: linear-gradient(135deg, var(--accent), var(--accent2));
    color: #fff;
    font-family: var(--font-head);
    font-weight: 600;
    font-size: 15px;
    letter-spacing: .04em;
    cursor: pointer;
    transition: opacity .2s, transform .1s;
    margin-bottom: 28px;
  }
  #translateBtn:disabled { opacity: .4; cursor: not-allowed; }
  #translateBtn:not(:disabled):hover { opacity: .9; transform: translateY(-1px); }
  #translateBtn:not(:disabled):active { transform: translateY(0); }

  /* Jobs list */
  #jobsList { display: flex; flex-direction: column; gap: 16px; }
  .job-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 16px 18px;
    animation: slideIn .2s ease;
  }
  .job-card .job-header { display: flex; align-items: flex-start; gap: 10px; margin-bottom: 10px; }
  .job-card .job-name { flex: 1; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .job-card .job-badge {
    font-size: 10px;
    letter-spacing: .07em;
    text-transform: uppercase;
    padding: 3px 8px;
    border-radius: 4px;
    flex-shrink: 0;
    font-weight: 500;
  }
  .badge-queued    { background: rgba(90,90,122,.3); color: var(--muted); }
  .badge-extracting{ background: rgba(251,191,36,.15); color: var(--warn); }
  .badge-converting{ background: rgba(251,191,36,.15); color: var(--warn); }
  .badge-translating{background: rgba(124,106,247,.2); color: var(--accent); }
  .badge-done      { background: rgba(74,222,128,.15); color: var(--success); }
  .badge-error     { background: rgba(248,113,113,.15); color: var(--error); }

  .job-message { font-size: 12px; color: var(--muted); margin-bottom: 10px; min-height: 16px; }

  /* Progress bar */
  .progress-wrap {
    height: 4px;
    background: var(--border);
    border-radius: 2px;
    overflow: hidden;
    margin-bottom: 10px;
  }
  .progress-bar {
    height: 100%;
    border-radius: 2px;
    background: linear-gradient(90deg, var(--accent), var(--accent2));
    transition: width .4s ease;
    width: 0%;
  }
  .progress-pct { font-size: 11px; color: var(--muted); text-align: right; margin-bottom: 8px; }

  /* Download link */
  .download-link {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    color: var(--success);
    text-decoration: none;
    font-size: 12px;
    padding: 6px 12px;
    border: 1px solid rgba(74,222,128,.3);
    border-radius: 6px;
    transition: background .2s;
  }
  .download-link:hover { background: rgba(74,222,128,.08); }

  .empty-state { text-align: center; color: var(--muted); font-size: 13px; padding: 20px 0; }
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>AI Subtitle<br/>Translator</h1>
    <p>Upload video files or SRT files — get translated subtitles back.</p>
  </header>

  <div class="controls">
    <label class="lang-label" for="langSelect">Translate to</label>
    <select id="langSelect">
      <option value="ja" selected>Japanese (ja)</option>
      <option value="zh">Chinese (zh)</option>
      <option value="ko">Korean (ko)</option>
      <option value="es">Spanish (es)</option>
      <option value="fr">French (fr)</option>
      <option value="de">German (de)</option>
      <option value="pt">Portuguese (pt)</option>
      <option value="ru">Russian (ru)</option>
      <option value="ar">Arabic (ar)</option>
      <option value="hi">Hindi (hi)</option>
      <option value="it">Italian (it)</option>
      <option value="nl">Dutch (nl)</option>
      <option value="pl">Polish (pl)</option>
      <option value="tr">Turkish (tr)</option>
      <option value="vi">Vietnamese (vi)</option>
      <option value="th">Thai (th)</option>
    </select>
  </div>

  <div class="dropzone" id="dropzone">
    <input type="file" id="fileInput" multiple accept=".srt,.mp4,.mkv"/>
    <span class="drop-icon">🎬</span>
    <p><strong>Drop files here</strong> or click to browse</p>
    <small>Supports .srt, .mp4, .mkv files — select multiple at once</small>
  </div>

  <div id="fileQueue"></div>

  <button id="translateBtn" disabled>Translate Files</button>

  <div id="jobsList"></div>
</div>

<script>
const dropzone   = document.getElementById('dropzone');
const fileInput  = document.getElementById('fileInput');
const fileQueue  = document.getElementById('fileQueue');
const translateBtn = document.getElementById('translateBtn');
const jobsList   = document.getElementById('jobsList');
const langSelect = document.getElementById('langSelect');

let pendingFiles = []; // Array of File objects

// ---------- Drag & Drop ----------
dropzone.addEventListener('dragover', e => { e.preventDefault(); dropzone.classList.add('drag-over'); });
dropzone.addEventListener('dragleave', () => dropzone.classList.remove('drag-over'));
dropzone.addEventListener('drop', e => {
  e.preventDefault();
  dropzone.classList.remove('drag-over');
  addFiles([...e.dataTransfer.files]);
});
fileInput.addEventListener('change', () => {
  addFiles([...fileInput.files]);
  fileInput.value = '';
});

function addFiles(files) {
  const allowed = ['.srt', '.mp4', '.mkv'];
  files.forEach(f => {
    const ext = f.name.slice(f.name.lastIndexOf('.')).toLowerCase();
    if (!allowed.includes(ext)) return;
    if (pendingFiles.find(x => x.name === f.name && x.size === f.size)) return; // dedupe
    pendingFiles.push(f);
  });
  renderQueue();
}

function removeFile(idx) {
  pendingFiles.splice(idx, 1);
  renderQueue();
}

function renderQueue() {
  fileQueue.innerHTML = '';
  pendingFiles.forEach((f, i) => {
    const item = document.createElement('div');
    item.className = 'file-item';
    const ext = f.name.slice(f.name.lastIndexOf('.')).toLowerCase();
    const icon = ext === '.srt' ? '📄' : '🎬';
    item.innerHTML = `
      <span class="file-icon">${icon}</span>
      <span class="file-name" title="${esc(f.name)}">${esc(f.name)}</span>
      <span class="file-size">${fmtSize(f.size)}</span>
      <button class="remove-btn" onclick="removeFile(${i})" title="Remove">✕</button>
    `;
    fileQueue.appendChild(item);
  });
  translateBtn.disabled = pendingFiles.length === 0;
}

function fmtSize(b) {
  if (b < 1024) return b + ' B';
  if (b < 1024*1024) return (b/1024).toFixed(1) + ' KB';
  return (b/1024/1024).toFixed(1) + ' MB';
}
function esc(s) { return s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

// ---------- Translate ----------
translateBtn.addEventListener('click', async () => {
  if (pendingFiles.length === 0) return;
  const lang = langSelect.value;
  const filesToSend = [...pendingFiles];
  pendingFiles = [];
  renderQueue();

  for (const file of filesToSend) {
    await submitFile(file, lang);
  }
});

async function submitFile(file, lang) {
  const jobId = createJobCard(file.name);
  const fd = new FormData();
  fd.append('file', file);
  fd.append('language', lang);
  fd.append('job_id', jobId);

  updateJob(jobId, { status: 'uploading', progress: 0, message: 'Uploading file…' });

  // XHR for upload progress
  await new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/translate');
    xhr.upload.addEventListener('progress', e => {
      if (e.lengthComputable) {
        const pct = Math.round((e.loaded / e.total) * 10); // upload = 0–10%
        updateJob(jobId, { progress: pct, message: `Uploading… ${Math.round(e.loaded/e.total*100)}%` });
      }
    });
    xhr.addEventListener('load', () => {
      try {
        const resp = JSON.parse(xhr.responseText);
        if (resp.error) {
          updateJob(jobId, { status: 'error', message: resp.error });
        } else {
          // Start polling
          pollJob(jobId, resp.job_id || jobId);
        }
      } catch(err) {
        updateJob(jobId, { status: 'error', message: 'Server error' });
      }
      resolve();
    });
    xhr.addEventListener('error', () => {
      updateJob(jobId, { status: 'error', message: 'Upload failed' });
      resolve();
    });
    xhr.send(fd);
  });
}

function pollJob(cardId, serverId) {
  const interval = setInterval(async () => {
    try {
      const res = await fetch(`/api/job/${serverId}`);
      const data = await res.json();
      updateJob(cardId, data);
      if (data.status === 'done' || data.status === 'error') {
        clearInterval(interval);
      }
    } catch(e) {
      clearInterval(interval);
      updateJob(cardId, { status: 'error', message: 'Polling failed' });
    }
  }, 800);
}

// ---------- Job cards ----------
const cardData = {};

function createJobCard(name) {
  const id = 'card_' + Math.random().toString(36).slice(2);
  cardData[id] = { status: 'queued', progress: 0, message: 'Queued…', name };

  const card = document.createElement('div');
  card.className = 'job-card';
  card.id = id;
  jobsList.prepend(card);
  renderCard(id);
  return id;
}

function updateJob(id, data) {
  if (!cardData[id]) return;
  Object.assign(cardData[id], data);
  renderCard(id);
}

function renderCard(id) {
  const d = cardData[id];
  const card = document.getElementById(id);
  if (!card) return;

  const badgeClass = `badge-${d.status || 'queued'}`;
  const statusLabel = (d.status || 'queued').toUpperCase();
  const downloadHtml = d.status === 'done' && d.result_filename
    ? `<a class="download-link" href="/api/download/${d.result_filename}" download="${d.result_filename}">
         ⬇ Download ${esc(d.result_filename)}
       </a>`
    : '';

  card.innerHTML = `
    <div class="job-header">
      <span class="job-name" title="${esc(d.name)}">${esc(d.name)}</span>
      <span class="job-badge ${badgeClass}">${statusLabel}</span>
    </div>
    <div class="job-message">${esc(d.message || '')}</div>
    <div class="progress-wrap"><div class="progress-bar" style="width:${d.progress||0}%"></div></div>
    <div class="progress-pct">${d.progress||0}%</div>
    ${downloadHtml}
  `;
}
</script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/api/translate", methods=["POST"])
def api_translate():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    f = request.files["file"]
    language = request.form.get("language", "ja")
    job_id = request.form.get("job_id", str(uuid.uuid4()))

    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400

    original_name = f.filename
    lower = original_name.lower()
    if not (lower.endswith(".srt") or lower.endswith(".mp4") or lower.endswith(".mkv")):
        return jsonify({"error": "Unsupported file type"}), 400

    # Save upload to temp file
    suffix = Path(original_name).suffix
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=_output_dir)
    f.save(tmp.name)
    tmp.close()

    with jobs_lock:
        jobs[job_id] = {
            "status": "queued",
            "progress": 0,
            "message": "Queued for processing…",
            "result_path": None,
            "result_filename": None,
        }

    t = threading.Thread(
        target=_process_file,
        args=(job_id, tmp.name, language, original_name),
        daemon=True,
    )
    t.start()

    return jsonify({"job_id": job_id})


@app.route("/api/job/<job_id>")
def api_job_status(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


@app.route("/api/download/<filename>")
def api_download(filename):
    # Basic path traversal guard
    safe_filename = Path(filename).name
    path = os.path.join(_output_dir, safe_filename)
    if not os.path.exists(path):
        return "File not found", 404
    return send_file(path, as_attachment=True, download_name=safe_filename)


# ---------------------------------------------------------------------------
# Entry point (standalone)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import pytesseract
    from modules.Loggers import configure_console_logger
    configure_console_logger()
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

    config = Config("config.ini")
    output_dir = os.path.join(os.path.dirname(__file__), "web_output")
    init_server(config, output_dir)
    host = config.config.get("web", "host", fallback="0.0.0.0")
    port = config.config.getint("web", "port", fallback=5000)
    print(f"Starting web server on http://{host}:{port}")
    app.run(host=host, port=port, debug=False)
