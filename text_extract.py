import io
import os
import re
import zipfile

import requests
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app_2 import MINERU_URL, UPLOAD_DIR


router = APIRouter()


@router.get("/text-extract-page", response_class=HTMLResponse)
async def text_extract_page():
    with open("templates/text_extract.html", "r", encoding="utf-8") as f:
        return f.read()


@router.post("/extract-text")
async def extract_text(request: Request):
    form = await request.form()
    uploaded = form.get("file")
    if not uploaded:
        return {"error": "missing file"}

    safe_name = os.path.basename(uploaded.filename or "document.pdf")
    allowed_exts = {
        ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp",
        ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx",
        ".txt", ".md", ".markdown", ".json",
    }
    if os.path.splitext(safe_name)[1].lower() not in allowed_exts:
        return {"error": "不支持的文件格式"}

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    file_path = os.path.join(UPLOAD_DIR, f"text_{safe_name}")
    with open(file_path, "wb") as f:
        f.write(await uploaded.read())

    markdown = call_mineru_markdown(file_path)
    return {
        "filename": safe_name,
        "text": markdown_to_plain_text(markdown),
    }


def call_mineru_markdown(file_path: str) -> str:
    with open(file_path, "rb") as f:
        files = [("files", (os.path.basename(file_path), f))]
        data = {
            "backend": "vlm-auto-engine",
            "response_format_zip": True,
            "return_middle_json": True,
            "return_model_output": False,
            "return_content_list": False,
            "return_images": False,
        }
        resp = requests.post(MINERU_URL, files=files, data=data, timeout=600)

    if resp.status_code != 200:
        raise RuntimeError(f"MinerU parse failed: {resp.status_code}")

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        for name in zf.namelist():
            lower = name.lower()
            if lower.endswith((".md", ".markdown")):
                return zf.read(name).decode("utf-8", errors="replace")
    return ""


def markdown_to_plain_text(markdown: str) -> str:
    text = str(markdown or "")
    text = re.sub(r"!\[[^\]]*]\([^)]*\)", "", text)
    text = re.sub(r"<img\b[^>]*>", "", text, flags=re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(p|div|tr|h[1-6]|li)>", "\n", text, flags=re.I)
    text = re.sub(r"</(td|th)>", "\t", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text, flags=re.M)
    text = re.sub(r"^\s{0,3}>\s?", "", text, flags=re.M)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.M)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.M)
    text = re.sub(r"\[([^\]]+)]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_~`]+", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
