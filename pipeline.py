"""Private inputs, public saved results, and one sequential queue worker."""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
import json
import logging
import os
from pathlib import Path
import subprocess
import tempfile
import time
import wave

from azure.core import MatchConditions
from azure.core.exceptions import ResourceExistsError, ResourceModifiedError, ResourceNotFoundError
from azure.identity import ManagedIdentityCredential
from azure.storage.blob import BlobServiceClient, ContentSettings
from azure.storage.queue import QueueClient, TextBase64EncodePolicy
import imageio_ffmpeg
import requests

from core import NOTES_SCHEMA, SYSTEM_PROMPT, normalize_transcript, public_metadata, validate_notes


def now():
    return datetime.now(timezone.utc).isoformat()


@lru_cache
def credential():
    return ManagedIdentityCredential()


class Store:
    def __init__(self):
        self.service = BlobServiceClient(os.environ["BLOB_SERVICE_URL"], credential=credential())

    def blob(self, name, public=False):
        return self.service.get_blob_client("$web" if public else "studynotes", name)

    def read(self, name, public=False):
        try:
            return json.loads(self.blob(name, public).download_blob().readall())
        except ResourceNotFoundError:
            return None

    def write(self, name, value, public=False, create=False):
        try:
            self.blob(name, public).upload_blob(json.dumps(value, ensure_ascii=False).encode(),
                overwrite=not create, content_settings=ContentSettings(
                    content_type="application/json; charset=utf-8", cache_control="no-store"))
            return True
        except ResourceExistsError:
            if create:
                return False
            raise

    def upload(self, name, content, content_type="application/octet-stream"):
        self.blob(name).upload_blob(content, overwrite=False,
            content_settings=ContentSettings(content_type=content_type))

    def download_to(self, name, target):
        with Path(target).open("wb") as output:
            self.blob(name).download_blob().readinto(output)

    def bytes(self, name):
        return self.blob(name).download_blob().readall()

    def register(self, meta):
        """Only upload handlers edit the catalog; ETags prevent lost entries."""
        target = self.blob("catalog.json", public=True)
        for _ in range(8):
            try:
                downloaded = target.download_blob()
                catalog = json.loads(downloaded.readall())
                etag = downloaded.properties.etag
            except ResourceNotFoundError:
                catalog, etag = {"lectures": []}, None
            if any(item["id"] == meta["id"] for item in catalog["lectures"]):
                return
            catalog["lectures"].insert(0, {key: meta[key] for key in ("id", "title", "created_at")})
            options = {"etag": etag, "match_condition": MatchConditions.IfNotModified} if etag else {}
            try:
                target.upload_blob(json.dumps(catalog, ensure_ascii=False).encode(), overwrite=etag is not None,
                    content_settings=ContentSettings(content_type="application/json; charset=utf-8", cache_control="no-store"),
                    **options)
                return
            except (ResourceExistsError, ResourceModifiedError):
                continue
        raise RuntimeError("Concurrent catalog update did not settle; try again later.")

    def enqueue(self, job):
        client = QueueClient(os.environ["QUEUE_SERVICE_URL"], "lectures", credential=credential(),
            message_encode_policy=TextBase64EncodePolicy())
        client.send_message(job, time_to_live=-1)


def publish_status(store, meta):
    meta["updated_at"] = now()
    store.write(f"jobs/{meta['id']}/metadata.json", meta)
    store.write(f"lectures/{meta['id']}.json", {"job": public_metadata(meta)}, public=True)


def prepare_audio(store, meta):
    folder = f"jobs/{meta['id']}"
    existing = store.read(folder + "/audio.json")
    if existing:
        return existing
    maximum = int(os.getenv("MAX_AUDIO_SECONDS", "5400"))
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / ("input" + Path(meta["filename"]).suffix)
        audio = Path(directory) / "audio.wav"
        store.download_to(meta["input_blob"], source)
        result = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-hide_banner",
            "-loglevel", "error", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000",
            "-c:a", "pcm_s16le", "-t", str(maximum + 1), str(audio)], capture_output=True, timeout=300)
        if result.returncode:
            raise ValueError("This file could not be read as an audio/video recording.")
        with wave.open(str(audio), "rb") as stream:
            duration = stream.getnframes() / stream.getframerate()
        if not 0.05 <= duration <= maximum:
            raise ValueError(f"Choose a recording between 0.05 and {maximum} seconds.")
        if audio.stat().st_size >= 250_000_000:
            raise ValueError("Prepared audio exceeds the Speech service's 250 MB limit.")
        with audio.open("rb") as content:
            store.upload(folder + "/audio.wav", content, "audio/wav")
        details = {"duration_seconds": duration, "sample_rate": 16000, "channels": 1, "sample_width": 2}
        store.write(folder + "/audio.json", details)
        return details


def paid_request(store, job, stage, call):
    """Cache successes; an uncertain attempt never silently issues another call."""
    folder = f"jobs/{job}/{stage}"
    saved = store.read(folder + "-raw.json")
    if saved is not None:
        return saved
    # Retrieve credentials before reserving a billable attempt.
    headers = {"Authorization": "Bearer " + credential().get_token("https://cognitiveservices.azure.com/.default").token}
    if not store.write(folder + "-attempt.json", {"reserved_at": now()}, create=True):
        raise ValueError("An earlier AI attempt has no saved result. Review it before starting a new trial.")
    started = time.monotonic()
    receipt = {"started_at": now(), "outcome": "unknown"}
    try:
        response = call(headers)
        receipt["http_status"] = response.status_code
        if not response.ok:
            receipt["outcome"] = "http_error"
            store.write(folder + "-error.json", {"http_status": response.status_code, "body": response.text[:20000]})
            raise ValueError(f"The {stage} service returned HTTP {response.status_code}; automatic retry is disabled.")
        raw = response.json()
        store.write(folder + "-raw.json", raw)
        receipt.update(outcome="saved", usage=raw.get("usage", {}))
        return raw
    finally:
        receipt["seconds"] = round(time.monotonic() - started, 3)
        store.write(folder + "-timing.json", receipt)


def transcribe(store, meta, audio):
    folder = f"jobs/{meta['id']}"
    saved = store.read(folder + "/transcript.json")
    if saved:
        return saved
    content = store.bytes(folder + "/audio.wav")
    raw = paid_request(store, meta["id"], "speech", lambda headers: requests.post(
        os.environ["AI_ENDPOINT"].rstrip("/") + "/speechtotext/transcriptions:transcribe?api-version=2025-10-15",
        headers=headers, files={"audio": ("audio.wav", content, "audio/wav"),
            "definition": (None, json.dumps({"locales": [meta["locale"]]}), "application/json")}, timeout=(15, 600)))
    transcript = normalize_transcript(raw, audio["duration_seconds"])
    store.write(folder + "/transcript.json", transcript)
    return transcript


def structure(store, meta, transcript):
    folder = f"jobs/{meta['id']}"
    saved = store.read(folder + "/notes.json")
    if saved:
        return saved
    content = json.dumps(transcript["segments"], ensure_ascii=False)
    if len(content) > int(os.getenv("MAX_TRANSCRIPT_CHARS", "350000")):
        raise ValueError("The transcript exceeds the configured note-generation input budget.")
    raw = paid_request(store, meta["id"], "summary", lambda headers: requests.post(
        os.environ["OPENAI_ENDPOINT"].rstrip("/") + "/openai/v1/chat/completions",
        headers={**headers, "Content-Type": "application/json"}, json={
            "model": os.environ["SUMMARY_DEPLOYMENT"], "reasoning_effort": "minimal",
            "max_completion_tokens": int(os.getenv("MAX_COMPLETION_TOKENS", "4096")),
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": content}],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "lecture_structure", "strict": True, "schema": NOTES_SCHEMA}}}, timeout=(15, 300)))
    choice = raw["choices"][0]
    if choice.get("finish_reason") != "stop" or choice["message"].get("refusal"):
        raise ValueError("The model did not finish; partial notes were not published.")
    notes = validate_notes(json.loads(choice["message"]["content"]), transcript)
    store.write(folder + "/notes.json", notes)
    return notes


def process(job, store=None, prepare=prepare_audio, speech=transcribe, notes=structure):
    store = store or Store()
    folder = f"jobs/{job}"
    meta = store.read(folder + "/metadata.json")
    if not meta:
        raise ValueError("Queue message has no corresponding upload.")
    if meta["status"] == "ready" or not store.write(folder + "/claim.json", {"claimed_at": now()}, create=True):
        return  # A duplicate delivery cannot start another worker for this job.
    started = time.monotonic()
    stages = {}
    try:
        for name, function in (("Preparing audio", lambda: prepare(store, meta)),
                               ("Transcribing", lambda: speech(store, meta, audio)),
                               ("Organizing the scriptum", lambda: notes(store, meta, transcript))):
            meta.update(status="processing", stage=name)
            publish_status(store, meta)
            tick = time.monotonic()
            value = function()
            stages[name] = round(time.monotonic() - tick, 3)
            if name == "Preparing audio":
                audio = value
                meta["duration_seconds"] = audio["duration_seconds"]
            elif name == "Transcribing":
                transcript = value
            else:
                guide = value
        meta.update(status="ready", stage="Ready to study", updated_at=now())
        store.write(folder + "/metadata.json", meta)
        store.write(f"lectures/{job}.json", {"job": public_metadata(meta), "transcript": transcript, "notes": guide}, public=True)
    except Exception as error:
        logging.exception("Lecture processing stopped for %s", job)
        meta.update(status="failed", stage="Processing stopped", error=str(error) if isinstance(error, ValueError) else
            "Processing stopped. The owner can inspect the saved job; no automatic AI retry will run.")
        publish_status(store, meta)
    finally:
        store.write(folder + "/timing.json", {"finished_at": now(), "worker_seconds": round(time.monotonic() - started, 3), "stages": stages})
