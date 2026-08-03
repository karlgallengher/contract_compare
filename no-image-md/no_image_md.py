import io
import os
import re
import zipfile

import requests
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app_2 import MINERU_URL, UPLOAD_DIR


router = APIRouter()


@router.get("/no-image-md-page", response_class=HTMLResponse)
async def no_image_md_page():
    with open("templates/no_image_md.html", "r", encoding="utf-8") as f:
        return f.read()


@router.post("/no-image-md")
async def no_image_md(request: Request):
    form = await request.form()
    uploaded = form.get("file")
    if not uploaded:
        return {"error": "missing file"}

    safe_name = os.path.basename(uploaded.filename or "document.pdf")
    if os.path.splitext(safe_name)[1].lower() != ".pdf":
        return {"error": "仅支持 PDF 文件"}

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    file_path = os.path.join(UPLOAD_DIR, f"no_image_md_{safe_name}")
    with open(file_path, "wb") as f:
        f.write(await uploaded.read())

    markdown = call_mineru_markdown(file_path)
    return {
        "filename": markdown_filename(safe_name),
        "markdown": remove_images_from_markdown(markdown),
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


def remove_images_from_markdown(markdown: str) -> str:
    result = str(markdown or "")
    result = re.sub(r"!\[[^\]]*]\([^)]*\)", "", result)
    result = re.sub(r"<img\b[^>]*>", "", result, flags=re.I)
    result = re.sub(r"[ \t]+\n", "\n", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def markdown_filename(filename: str) -> str:
    base = os.path.basename(filename or "mineru_result")
    base = re.sub(r"\.[^.]+$", "", base)
    base = re.sub(r'[\\/:*?"<>|]+', "_", base).strip()
    return f"{base or 'mineru_result'}_no_images.md"
