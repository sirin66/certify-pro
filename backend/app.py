"""
CertifyPro - Automated Certificate Generator & Google Drive Uploader
=====================================================================
Built with Flask, Pillow, Pandas, and the Google Drive API Client.
"""

import io
import os
import re
import json
import zipfile
import logging
from pathlib import Path

import pandas as pd
import requests
from PIL import Image, ImageDraw, ImageFont
from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_cors import CORS

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# ── Flask Setup ──────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder="../frontend", static_url_path="")
CORS(app, resources={r"/*": {"origins": "*"}})

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
FONTS_DIR = BASE_DIR / "fonts"
UPLOAD_DIR = BASE_DIR / "uploads"
GENERATED_DIR = BASE_DIR / "generated_output"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
FONTS_DIR.mkdir(parents=True, exist_ok=True)
GENERATED_DIR.mkdir(parents=True, exist_ok=True)

SCOPES = ["https://www.googleapis.com/auth/drive"]
SERVICE_ACCOUNT_FILE = os.environ.get(
    "GOOGLE_SERVICE_ACCOUNT_JSON",
    str(BASE_DIR / "service_account.json")
)

WIDTH = 3508
HEIGHT = 2480


# ── Safe String Helper (Prevents 'NoneType' object has no attribute 'strip') ──
def safe_str(val, default="") -> str:
    if val is None:
        return default
    return str(val).strip()


# ── Global Error Handler ─────────────────────────────────────────────────────
@app.errorhandler(Exception)
def handle_exception(e):
    logger.exception("Server Exception")
    resp = jsonify({"error": str(e)})
    resp.headers.add("Access-Control-Allow-Origin", "*")
    return resp, 400


# ── Google Drive Helpers ─────────────────────────────────────────────────────
def get_service_account_info():
    p = Path(SERVICE_ACCOUNT_FILE)
    if not p.exists():
        return {"exists": False, "email": None}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {"exists": True, "email": data.get("client_email")}
    except Exception:
        return {"exists": False, "email": None}


def get_drive_service():
    if not Path(SERVICE_ACCOUNT_FILE).exists():
        raise FileNotFoundError("Google Cloud Service Account key (service_account.json) is not configured.")
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds)


def upload_to_drive(service, file_bytes: bytes, filename: str, folder_id: str) -> str:
    clean_folder_id = safe_str(folder_id)
    m_folder = re.search(r"folders/([a-zA-Z0-9_-]+)", clean_folder_id)
    if m_folder:
        clean_folder_id = m_folder.group(1)

    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype="image/png", resumable=False)
    file_metadata = {"name": filename, "parents": [clean_folder_id]}
    
    uploaded = service.files().create(body=file_metadata, media_body=media, fields="id, webViewLink").execute()
    try:
        service.permissions().create(fileId=uploaded["id"], body={"type": "anyone", "role": "reader"}).execute()
    except Exception:
        pass
    return uploaded.get("webViewLink", "")


# ── CSV & Spreadsheet Helpers ────────────────────────────────────────────────
def extract_google_ids(raw_url: str):
    url_clean = safe_str(raw_url)
    m_sheet = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url_clean)
    if m_sheet:
        m_gid = re.search(r"[#&?]gid=(\d+)", url_clean)
        return "sheet", m_sheet.group(1), m_gid.group(1) if m_gid else "0"

    m_file = re.search(r"/file/d/([a-zA-Z0-9_-]+)", url_clean) or re.search(r"[?&]id=([a-zA-Z0-9_-]+)", url_clean)
    if m_file:
        return "drive_file", m_file.group(1), "0"

    return "plain", url_clean, "0"


def fetch_raw_dataframe(url: str) -> pd.DataFrame:
    kind, file_id, gid = extract_google_ids(url)

    if kind in ("sheet", "drive_file") and Path(SERVICE_ACCOUNT_FILE).exists():
        try:
            drive_svc = get_drive_service()
            if kind == "sheet":
                content = drive_svc.files().export_media(fileId=file_id, mimeType="text/csv").execute()
            else:
                content = drive_svc.files().get_media(fileId=file_id).execute()
            return pd.read_csv(io.BytesIO(content))
        except Exception:
            pass

    if kind == "sheet":
        csv_url = f"https://docs.google.com/spreadsheets/d/{file_id}/gviz/tq?tqx=out:csv&gid={gid}"
    elif kind == "drive_file":
        csv_url = f"https://drive.google.com/uc?export=download&id={file_id}"
    else:
        csv_url = safe_str(url)

    response = requests.get(csv_url, timeout=25)
    response.raise_for_status()
    return pd.read_csv(io.StringIO(response.text))


def detect_name_column(columns, chosen_col=None) -> str:
    chosen_clean = safe_str(chosen_col)
    if chosen_clean and chosen_clean in columns:
        return chosen_clean

    candidates = ["full name", "student name", "name", "participant name", "candidate name", "student", "your name"]
    col_lookup = {c.strip().lower(): c for c in columns}

    for cand in candidates:
        if cand in col_lookup:
            return col_lookup[cand]

    for cand in candidates:
        for clean_c, orig_c in col_lookup.items():
            if cand in clean_c:
                return orig_c

    if len(columns) > 1 and "timestamp" in columns[0].lower():
        return columns[1]
    return columns[0]


# ── Typography & Rendering (RGB Safe) ────────────────────────────────────────
def get_font(size: int, font_name: str = "Cinzel-Bold.ttf"):
    font_file = FONTS_DIR / font_name
    if font_file.exists():
        try:
            return ImageFont.truetype(str(font_file), size)
        except Exception:
            pass

    for fallback in ["arial.ttf", "calibri.ttf", "DejaVuSans.ttf"]:
        try:
            return ImageFont.truetype(fallback, size)
        except Exception:
            continue
    return ImageFont.load_default()


def fit_text_to_width(draw, text: str, max_width: int, start_size: int = 150, min_size: int = 36, font_name: str = "Cinzel-Bold.ttf"):
    size = start_size
    text_clean = safe_str(text)
    while size >= min_size:
        font = get_font(size, font_name)
        bbox = draw.textbbox((0, 0), text_clean, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            return font, bbox[2] - bbox[0], bbox[3] - bbox[1]
        size -= 4
    font = get_font(min_size, font_name)
    bbox = draw.textbbox((0, 0), text_clean, font=font)
    return font, bbox[2] - bbox[0], bbox[3] - bbox[1]


def render_certificate_content(img: Image.Image, student_name: str, event: str, config: dict) -> Image.Image:
    draw = ImageDraw.Draw(img)
    usable_width = int(WIDTH * 0.84)
    student_clean = safe_str(student_name)
    event_clean = safe_str(event)

    if not config.get("hide_meta"):
        label_font = get_font(52, config.get("label_font", "arial.ttf"))
        label_text = config.get("label_text", "THIS CERTIFICATE IS PROUDLY PRESENTED TO")
        l_box = draw.textbbox((0, 0), label_text, font=label_font)
        draw.text(((WIDTH - (l_box[2] - l_box[0])) // 2, int(HEIGHT * 0.38)), label_text, font=label_font, fill=config["label_color"])

    name_y = int(HEIGHT * config.get("name_y_ratio", 0.46))
    name_font, n_w, n_h = fit_text_to_width(
        draw, student_clean, usable_width, start_size=config.get("name_size", 155), min_size=42, font_name=config.get("name_font", "Cinzel-Bold.ttf")
    )
    shadow_fill = "#1a1a1a" if config["name_color"] == "#ffffff" else "#e2e8f0"
    draw.text(((WIDTH - n_w) // 2 + 3, name_y + 3), student_clean, font=name_font, fill=shadow_fill)
    draw.text(((WIDTH - n_w) // 2, name_y), student_clean, font=name_font, fill=config["name_color"])

    if not config.get("hide_meta") and event_clean:
        line_y = name_y + n_h + 45
        draw.line([(WIDTH // 2 - 320, line_y), (WIDTH // 2 + 320, line_y)], fill=config["accent_color"], width=5)

        reason_font = get_font(48, config.get("label_font", "arial.ttf"))
        reason_text = "for outstanding performance and active participation in"
        r_box = draw.textbbox((0, 0), reason_text, font=reason_font)
        draw.text(((WIDTH - (r_box[2] - r_box[0])) // 2, line_y + 40), reason_text, font=reason_font, fill=config["label_color"])

        event_font, e_w, e_h = fit_text_to_width(
            draw, event_clean, usable_width, start_size=105, min_size=34, font_name=config.get("event_font", "arial.ttf")
        )
        draw.text(((WIDTH - e_w) // 2, line_y + 130), event_clean, font=event_font, fill=config["event_color"])

    return img


def generate_professional_template(student_name: str, event: str) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), "#0c172e")
    draw = ImageDraw.Draw(img)
    draw.rectangle([35, 35, WIDTH - 35, HEIGHT - 35], outline="#d4af37", width=22)
    draw.rectangle([75, 75, WIDTH - 75, HEIGHT - 75], outline="#d4af37", width=4)
    draw.rectangle([0, int(HEIGHT * 0.09), WIDTH, int(HEIGHT * 0.23)], fill="#132347")
    title_font = get_font(120, "Cinzel-Bold.ttf")
    t_box = draw.textbbox((0, 0), "CERTIFICATE OF ACHIEVEMENT", font=title_font)
    draw.text(((WIDTH - (t_box[2] - t_box[0])) // 2, int(HEIGHT * 0.12)), "CERTIFICATE OF ACHIEVEMENT", font=title_font, fill="#d4af37")

    return render_certificate_content(img, student_name, event, {
        "name_color": "#ffffff", "event_color": "#f3ce65", "label_color": "#9eb1d4", "accent_color": "#d4af37"
    })


def generate_creative_template(student_name: str, event: str) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), "#17062e")
    draw = ImageDraw.Draw(img)
    for y in range(HEIGHT):
        ratio = y / HEIGHT
        draw.line([(0, y), (WIDTH, y)], fill=(int(23 + ratio * 55), int(6 + ratio * 18), int(46 + ratio * 66)))

    title_font = get_font(110, "Cinzel-Bold.ttf")
    t_box = draw.textbbox((0, 0), "CERTIFICATE OF EXCELLENCE", font=title_font)
    draw.text(((WIDTH - (t_box[2] - t_box[0])) // 2, int(HEIGHT * 0.14)), "CERTIFICATE OF EXCELLENCE", font=title_font, fill="#ffd166")

    return render_certificate_content(img, student_name, event, {
        "name_color": "#ffffff", "event_color": "#ffd166", "label_color": "#e0c3fc", "accent_color": "#ff70a6"
    })


def generate_minimalist_template(student_name: str, event: str) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), "#fcfbf7")
    draw = ImageDraw.Draw(img)
    draw.rectangle([50, 50, WIDTH - 50, HEIGHT - 50], outline="#1b4332", width=6)
    title_font = get_font(105, "Cinzel-Bold.ttf")
    t_box = draw.textbbox((0, 0), "Certificate of Completion", font=title_font)
    draw.text(((WIDTH - (t_box[2] - t_box[0])) // 2, int(HEIGHT * 0.15)), "Certificate of Completion", font=title_font, fill="#1b4332")

    return render_certificate_content(img, student_name, event, {
        "name_color": "#1b263b", "event_color": "#1b4332", "label_color": "#6c757d", "accent_color": "#1b4332"
    })


def generate_custom_template(student_name: str, event: str, bg_path: str = None, custom_settings: dict = None) -> Image.Image:
    if bg_path and Path(bg_path).exists():
        bg_img = Image.open(bg_path).convert("RGB").resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    else:
        # Graceful fallback: Clean parchment canvas with gold border
        bg_img = Image.new("RGB", (WIDTH, HEIGHT), "#fdfcf9")
        draw = ImageDraw.Draw(bg_img)
        draw.rectangle([60, 60, WIDTH - 60, HEIGHT - 60], outline="#c5a059", width=12)

    settings = custom_settings or {}
    text_color = safe_str(settings.get("text_color"), "#111827")
    hide_meta = settings.get("only_name", True)

    return render_certificate_content(bg_img, student_name, event, {
        "name_color": text_color,
        "event_color": text_color,
        "label_color": "#4b5563",
        "accent_color": text_color,
        "hide_meta": hide_meta,
        "name_y_ratio": float(settings.get("name_y", 0.48)),
        "name_size": int(settings.get("name_size", 160))
    })


def build_certificate_png_bytes(student_name: str, event: str, template: str, bg_path: str = None, custom_settings: dict = None) -> bytes:
    if template == "professional":
        cert = generate_professional_template(student_name, event)
    elif template == "creative":
        cert = generate_creative_template(student_name, event)
    elif template == "minimalist":
        cert = generate_minimalist_template(student_name, event)
    else:
        cert = generate_custom_template(student_name, event, bg_path, custom_settings)

    buf = io.BytesIO()
    cert.save(buf, format="PNG", quality=95)
    return buf.getvalue()


# ── REST API Endpoints ───────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/status", methods=["GET"])
def get_status():
    sa_info = get_service_account_info()
    return jsonify({
        "service_account_configured": sa_info["exists"],
        "service_account_email": sa_info["email"]
    })


@app.route("/api/upload-service-account", methods=["POST"])
def upload_service_account():
    if "key_file" not in request.files:
        return jsonify({"error": "No JSON key file provided."}), 400

    f = request.files["key_file"]
    try:
        content = json.loads(f.read().decode("utf-8"))
        if "client_email" not in content or "private_key" not in content:
            return jsonify({"error": "Invalid Service Account key format."}), 400

        with open(SERVICE_ACCOUNT_FILE, "w", encoding="utf-8") as out:
            json.dump(content, out, indent=2)

        return jsonify({"message": "Key configured successfully!", "email": content.get("client_email")})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/preview-csv", methods=["POST"])
def preview_csv():
    data = request.get_json(silent=True) or {}
    url = safe_str(data.get("url"))
    chosen_col = safe_str(data.get("name_column")) or None

    if not url:
        return jsonify({"error": "Please provide a valid spreadsheet link."}), 400

    try:
        raw_df = fetch_raw_dataframe(url)
        all_columns = list(raw_df.columns)
        name_col = detect_name_column(all_columns, chosen_col)

        valid_df = raw_df[raw_df[name_col].notna()].copy()
        valid_df[name_col] = valid_df[name_col].astype(str).str.strip()
        valid_df = valid_df[valid_df[name_col] != ""]

        all_names = valid_df[name_col].tolist()
        preview_data = [{"Student Name": val} for val in all_names[:10]]

        return jsonify({
            "total_count": len(valid_df),
            "columns": all_columns,
            "detected_name_column": name_col,
            "all_student_names": all_names,
            "preview": preview_data
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/upload-template", methods=["POST"])
def upload_template():
    if "template_file" not in request.files:
        return jsonify({"error": "No template image provided."}), 400

    file = request.files["template_file"]
    ext = file.filename.lower().split(".")[-1]
    safe_filename = f"custom_template_{os.urandom(4).hex()}.{ext}"
    dest_path = UPLOAD_DIR / safe_filename
    file.save(dest_path)
    return jsonify({"template_id": safe_filename, "filename": file.filename})


@app.route("/api/generate", methods=["POST"])
def generate():
    data = request.get_json(silent=True) or {}
    student_list = data.get("students", [])
    csv_url = safe_str(data.get("csv_url"))
    event_name = safe_str(data.get("event_name"), "Event")
    name_col_choice = safe_str(data.get("name_column")) or None
    template = safe_str(data.get("template"), "professional").lower()
    template_id = safe_str(data.get("template_id"))
    folder_id = safe_str(data.get("folder_id"))
    custom_settings = data.get("custom_settings", {})
    action_type = safe_str(data.get("action"), "zip").lower()

    # Retrieve student names (from cached list in request or via spreadsheet)
    students_to_process = []
    if student_list and len(student_list) > 0:
        students_to_process = student_list
    elif csv_url:
        try:
            raw_df = fetch_raw_dataframe(csv_url)
            name_col = detect_name_column(list(raw_df.columns), name_col_choice)
            valid_df = raw_df[raw_df[name_col].notna()].copy()
            valid_df[name_col] = valid_df[name_col].astype(str).str.strip()
            students_to_process = valid_df[valid_df[name_col] != ""][name_col].tolist()
        except Exception as exc:
            return jsonify({"error": f"Failed reading spreadsheet: {exc}"}), 400

    if not students_to_process:
        return jsonify({"error": "No student names found to generate certificates."}), 400

    bg_path = None
    if template == "custom" and template_id:
        bg_path = str(UPLOAD_DIR / template_id)

    clean_event = re.sub(r"[^\w\s-]", "", event_name).strip().replace(" ", "_") or "Event"

    # Handle Google Drive Service Connection
    drive_service = None
    if action_type == "drive":
        if folder_id:
            try:
                drive_service = get_drive_service()
            except Exception as drive_init_err:
                logger.warning(f"Drive init failed: {drive_init_err}. Auto-switching to ZIP.")
                action_type = "zip"
        else:
            action_type = "zip"

    results = []
    errors = []
    zip_buffer = io.BytesIO() if action_type == "zip" else None
    zip_file = zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) if action_type == "zip" else None

    for student in students_to_process:
        student_str = safe_str(student)
        clean_name = re.sub(r"[^\w\s-]", "", student_str).strip().replace(" ", "_")
        filename = f"{clean_name}_{clean_event}_Certificate.png"

        try:
            image_bytes = build_certificate_png_bytes(student_str, event_name, template, bg_path, custom_settings)

            if action_type == "drive" and drive_service:
                link = upload_to_drive(drive_service, image_bytes, filename, folder_id)
                results.append({"student_name": student_str, "event": event_name, "filename": filename, "drive_link": link})
            else:
                zip_file.writestr(filename, image_bytes)
                results.append({"student_name": student_str, "event": event_name, "filename": filename})
        except Exception as gen_err:
            errors.append({"student_name": student_str, "error": str(gen_err)})

    if action_type == "zip" or not drive_service:
        zip_file.close()
        zip_buffer.seek(0)
        zip_filename = f"certificates_{clean_event}.zip"
        zip_disk_path = GENERATED_DIR / zip_filename
        with open(zip_disk_path, "wb") as f_out:
            f_out.write(zip_buffer.getvalue())

        return jsonify({
            "success_count": len(results),
            "failed_count": len(errors),
            "download_zip_url": f"/api/download-zip/{zip_filename}",
            "fallback_to_zip": (safe_str(data.get("action")) == "drive" and not drive_service),
            "results": results,
            "errors": errors
        })

    return jsonify({
        "success_count": len(results),
        "failed_count": len(errors),
        "results": results,
        "errors": errors
    })


@app.route("/api/download-zip/<filename>", methods=["GET"])
def download_zip(filename):
    safe_name = os.path.basename(filename)
    file_path = GENERATED_DIR / safe_name
    if not file_path.exists():
        return jsonify({"error": "File not found"}), 404
    return send_file(file_path, as_attachment=True, download_name=safe_name)


if __name__ == "__main__":
    try:
        import antigravity
    except ImportError:
        pass
    print("Starting CertifyPro server at http://127.0.0.1:5000 ...")
    app.run(host="0.0.0.0", port=5000, debug=True)
