import os
import time
import requests
from pathlib import Path
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv, set_key

load_dotenv()

app = Flask(__name__)

ENV_PATH = Path(__file__).parent / ".env"
API_BASE = "https://api.elevenlabs.io/v1"


def get_api_key():
    return os.getenv("ELEVENLABS_API_KEY", "")


def get_paid_key():
    return os.getenv("ELEVENLABS_PAID_KEY", "")


def api_headers(key=None):
    return {
        "xi-api-key": key or get_api_key(),
        "Content-Type": "application/json",
    }


@app.route("/")
def index():
    return render_template("index.html", api_key=get_api_key(), paid_key=get_paid_key())


@app.route("/api/save-key", methods=["POST"])
def save_key():
    data = request.json
    key = data.get("api_key", "").strip()
    if not key:
        return jsonify({"error": "API key cannot be empty"}), 400
    set_key(str(ENV_PATH), "ELEVENLABS_API_KEY", key)
    os.environ["ELEVENLABS_API_KEY"] = key
    return jsonify({"success": True})


@app.route("/api/save-paid-key", methods=["POST"])
def save_paid_key():
    data = request.json
    key = data.get("paid_key", "").strip()
    if not key:
        return jsonify({"error": "Paid key cannot be empty"}), 400
    set_key(str(ENV_PATH), "ELEVENLABS_PAID_KEY", key)
    os.environ["ELEVENLABS_PAID_KEY"] = key
    return jsonify({"success": True})


@app.route("/api/voices")
def list_voices():
    key = get_api_key()
    if not key:
        return jsonify({"error": "API key not set"}), 400
    resp = requests.get(f"{API_BASE}/voices", headers={"xi-api-key": key})
    if resp.status_code != 200:
        return jsonify({"error": f"ElevenLabs API error: {resp.status_code}"}), resp.status_code
    voices = []
    for v in resp.json().get("voices", []):
        labels = v.get("labels", {})
        lang = labels.get("language", "")
        accent = labels.get("accent", "")
        label_parts = [p for p in [lang, accent] if p]
        display = f"{v['name']} ({', '.join(label_parts)})" if label_parts else v["name"]
        voices.append({
            "voice_id": v["voice_id"],
            "name": v["name"],
            "display": display,
        })
    voices.sort(key=lambda x: x["name"].lower())
    return jsonify({"voices": voices})


@app.route("/api/generate", methods=["POST"])
def generate():
    data = request.json
    voice_id = data.get("voice_id", "")
    voice_settings = data.get("voice_settings", {})
    vo_jobs = data.get("vo_jobs", [])
    sfx_jobs = data.get("sfx_jobs", [])
    key = get_api_key()
    paid_key = get_paid_key()
    vo_key = paid_key if paid_key else key

    if not key and not paid_key:
        return jsonify({"error": "API key not set"}), 400

    results = []

    # Process VO jobs
    for job in vo_jobs:
        filename = job.get("filename", "").strip()
        folder = job.get("folder", "").strip()
        text = job.get("text", "").strip()

        if not all([filename, folder, text]):
            results.append({
                "type": "VO",
                "filename": filename,
                "status": "failed",
                "error": "Missing filename, folder, or text",
            })
            continue

        if not filename.lower().endswith(".mp3"):
            filename += ".mp3"

        dest = Path(folder) / filename

        if dest.exists():
            size_kb = round(dest.stat().st_size / 1024, 1)
            results.append({
                "type": "VO",
                "filename": filename,
                "status": "skipped",
                "size_kb": size_kb,
                "path": str(dest),
            })
            continue

        try:
            Path(folder).mkdir(parents=True, exist_ok=True)
            payload = {
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": voice_settings.get("stability", 0.75),
                    "similarity_boost": voice_settings.get("similarity_boost", 0.85),
                    "style": voice_settings.get("style", 0.4),
                    "use_speaker_boost": voice_settings.get("use_speaker_boost", True),
                },
            }
            resp = requests.post(
                f"{API_BASE}/text-to-speech/{voice_id}",
                headers=api_headers(vo_key),
                json=payload,
            )
            if resp.status_code != 200:
                error_msg = resp.text[:200]
                results.append({
                    "type": "VO",
                    "filename": filename,
                    "status": "failed",
                    "error": f"API {resp.status_code}: {error_msg}",
                })
            else:
                dest.write_bytes(resp.content)
                size_kb = round(len(resp.content) / 1024, 1)
                results.append({
                    "type": "VO",
                    "filename": filename,
                    "status": "success",
                    "size_kb": size_kb,
                    "path": str(dest),
                })
        except Exception as e:
            results.append({
                "type": "VO",
                "filename": filename,
                "status": "failed",
                "error": str(e),
            })

        time.sleep(1.5)

    # Process SFX jobs
    for job in sfx_jobs:
        filename = job.get("filename", "").strip()
        folder = job.get("folder", "").strip()
        prompt = job.get("prompt", "").strip()
        duration = job.get("duration", 5)

        if not all([filename, folder, prompt]):
            results.append({
                "type": "SFX",
                "filename": filename,
                "status": "failed",
                "error": "Missing filename, folder, or prompt",
            })
            continue

        if not filename.lower().endswith(".mp3"):
            filename += ".mp3"

        dest = Path(folder) / filename

        if dest.exists():
            size_kb = round(dest.stat().st_size / 1024, 1)
            results.append({
                "type": "SFX",
                "filename": filename,
                "status": "skipped",
                "size_kb": size_kb,
                "path": str(dest),
            })
            continue

        try:
            Path(folder).mkdir(parents=True, exist_ok=True)
            payload = {
                "text": prompt,
                "duration_seconds": float(duration),
                "prompt_influence": 0.3,
            }
            resp = requests.post(
                f"{API_BASE}/sound-generation",
                headers=api_headers(),
                json=payload,
            )
            if resp.status_code != 200:
                error_msg = resp.text[:200]
                results.append({
                    "type": "SFX",
                    "filename": filename,
                    "status": "failed",
                    "error": f"API {resp.status_code}: {error_msg}",
                })
            else:
                dest.write_bytes(resp.content)
                size_kb = round(len(resp.content) / 1024, 1)
                results.append({
                    "type": "SFX",
                    "filename": filename,
                    "status": "success",
                    "size_kb": size_kb,
                    "path": str(dest),
                })
        except Exception as e:
            results.append({
                "type": "SFX",
                "filename": filename,
                "status": "failed",
                "error": str(e),
            })

        time.sleep(1.5)

    # Summary
    vo_success = sum(1 for r in results if r["type"] == "VO" and r["status"] == "success")
    sfx_success = sum(1 for r in results if r["type"] == "SFX" and r["status"] == "success")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    failed = sum(1 for r in results if r["status"] == "failed")

    return jsonify({
        "results": results,
        "summary": {
            "vo_success": vo_success,
            "sfx_success": sfx_success,
            "skipped": skipped,
            "failed": failed,
            "total": len(results),
        },
    })


if __name__ == "__main__":
    from waitress import serve
    print("AlRomaih Audio Generator running on http://localhost:5050")
    serve(app, host="0.0.0.0", port=5050)
