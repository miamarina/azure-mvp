"""Anonymous upload + one queue worker. Readers use static saved JSON."""
from functools import lru_cache
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import re
from urllib.parse import unquote

import azure.functions as func

from core import EXTENSIONS, LOCALES, VERSION, job_id, nonempty, source_url
from pipeline import Store, now, process, publish_status

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


@lru_cache
def storage():
    return Store()


def response(value, status=200):
    return func.HttpResponse(json.dumps(value, ensure_ascii=False), status_code=status,
        mimetype="application/json", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@app.route(route="health", methods=["GET"])
def health(req):
    return response({"status": "ok", "application": "StudyNotes", "version": VERSION,
        "max_upload_bytes": int(os.getenv("MAX_UPLOAD_BYTES", "209715200")),
        "max_audio_seconds": int(os.getenv("MAX_AUDIO_SECONDS", "5400"))})


@app.route(route="jobs", methods=["POST"])
def upload(req):
    maximum = int(os.getenv("MAX_UPLOAD_BYTES", "209715200"))
    try:
        length = int(req.headers.get("Content-Length", "0"))
        if length < 0:
            raise ValueError("Invalid content length.")
        if length > maximum:
            return response({"error": f"Choose a file no larger than {maximum // 1048576} MiB."}, 413)
        data = req.get_body()
        if not data or len(data) > maximum:
            return response({"error": f"Choose a nonempty file no larger than {maximum // 1048576} MiB."}, 413)
        filename = re.split(r"[/\\]", unquote(req.headers.get("X-Filename", "lecture.mp4")))[-1][:180]
        if Path(filename).suffix.lower() not in EXTENSIONS:
            raise ValueError("Choose MP4, WAV, MP3, M4A, WebM, OGG or FLAC.")
        locale = req.params.get("locale", "en-US")
        if locale not in LOCALES:
            raise ValueError("Choose English or German.")
        source = source_url(unquote(req.headers.get("X-Source-Url", "")))
        offset = float(req.headers.get("X-Source-Offset", "0"))
        if not math.isfinite(offset) or not 0 <= offset <= 86400:
            raise ValueError("Provide a valid source offset in seconds.")
        title = nonempty(unquote(req.headers.get("X-Title", "")) or Path(filename).stem, 160)
        trial = req.params.get("trial", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{0,80}", trial):
            raise ValueError("Trial IDs may contain only letters, digits, underscores and hyphens (up to 80).")
        attribution = unquote(req.headers.get("X-Attribution", ""))[:1000]
        job = job_id(data, locale, trial)
    except (ValueError, OverflowError):
        return response({"error": "Check the filename, title, source URL, language, offset and trial ID."}, 400)
    meta = {"id": job, "title": title, "filename": filename, "locale": locale,
        "source_url": source, "source_offset_seconds": offset, "attribution": attribution,
        "created_at": now(), "status": "queued", "stage": "Waiting for a worker",
        "input_blob": f"jobs/{job}/input{Path(filename).suffix.lower()}",
        "input_sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data), "trial_id": trial}
    store = storage()
    try:
        if not store.write(f"jobs/{job}/metadata.json", meta, create=True):
            existing = store.read(f"jobs/{job}/metadata.json")
            return response({"id": job, "status": existing["status"], "duplicate": True})
        store.upload(meta["input_blob"], data)
        publish_status(store, meta)
        store.register(meta)
        store.enqueue(job)
    except Exception:
        logging.exception("Could not queue %s", job)
        meta.update(status="failed", stage="Upload could not be queued", error="Upload could not be queued. Inspect this job before resubmitting.")
        publish_status(store, meta)
        return response({"id": job, "error": meta["error"]}, 500)
    return response({"id": job, "status": "queued", "duplicate": False}, 202)


@app.queue_trigger(arg_name="message", queue_name="lectures", connection="AzureWebJobsStorage")
def process_lecture(message: func.QueueMessage):
    job = message.get_body().decode("utf-8")
    if not re.fullmatch(r"[0-9a-f]{40}", job):
        raise ValueError("Invalid lecture ID in queue.")
    process(job)
