# import base64
# import io
# import json
# import os
# import zipfile

# import fitz
# import requests
# from fastapi import FastAPI, Request
# from fastapi.responses import HTMLResponse

# from app_2 import (
#     MINERU_URL,
#     UPLOAD_DIR,
#     call_mineru,
#     pdf_to_highlighted_images,
#     run_pipeline,
# )

# app = FastAPI()
# os.makedirs(UPLOAD_DIR, exist_ok=True)
# os.makedirs("output", exist_ok=True)


# @app.get("/", response_class=HTMLResponse)
# async def index():
#     with open("templates/home.html", "r", encoding="utf-8") as f:
#         return f.read()


# @app.get("/compare-page", response_class=HTMLResponse)
# async def compare_page():
#     with open("templates/index.html", "r", encoding="utf-8") as f:
#         return f.read()


# @app.post("/parse")
# async def parse_document(request: Request):
#     form = await request.form()
#     uploaded = form.get("file")
#     output_format = form.get("format") or "markdown"
#     if not uploaded:
#         return {"error": "missing file"}

#     safe_name = os.path.basename(uploaded.filename or "document.pdf")
#     parse_path = os.path.join(UPLOAD_DIR, f"parse_{safe_name}")
#     with open(parse_path, "wb") as f:
#         f.write(await uploaded.read())

#     parsed = call_mineru_document(parse_path, output_format)
#     return {
#         "filename": safe_name,
#         "format": parsed["format"],
#         "content": parsed["content"],
#         "source": build_source_preview(parse_path),
#     }


# @app.post("/compare")
# async def compare(request: Request):
#     form = await request.form()
#     fb = form.get("file_before")
#     fa = form.get("file_after")
#     pb = os.path.join(UPLOAD_DIR, "before.pdf")
#     pa = os.path.join(UPLOAD_DIR, "after.pdf")
#     with open(pb, "wb") as f:
#         f.write(await fb.read())
#     with open(pa, "wb") as f:
#         f.write(await fa.read())

#     lb = call_mineru(pb)
#     la = call_mineru(pa)
#     diffs = run_pipeline(lb, la, pb, pa)
#     return {
#         "diffs": diffs,
#         "before_images": pdf_to_highlighted_images(pb, diffs, "before"),
#         "after_images": pdf_to_highlighted_images(pa, diffs, "after"),
#     }


# def call_mineru_document(file_path: str, output_format: str = "markdown") -> dict:
#     with open(file_path, "rb") as f:
#         files = [("files", (os.path.basename(file_path), f))]
#         data = {
#             "backend": "pipeline",
#             "response_format_zip": True,
#             "return_middle_json": True,
#             "return_model_output": False,
#             "return_content_list": False,
#         }
#         resp = requests.post(MINERU_URL, files=files, data=data, timeout=600)

#     if resp.status_code != 200:
#         raise RuntimeError(f"MinerU parse failed: {resp.status_code}")

#     layout = {}
#     markdown = ""
#     with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
#         for name in zf.namelist():
#             lower = name.lower()
#             if lower.endswith(("middle.json", "layout.json")) and not layout:
#                 layout = json.loads(zf.read(name).decode("utf-8"))
#             elif lower.endswith((".md", ".markdown")) and not markdown:
#                 markdown = zf.read(name).decode("utf-8", errors="replace")

#     if layout:
#         base_name = os.path.basename(file_path).rsplit(".", 1)[0]
#         save_path = os.path.join("output", f"{base_name}_parse_layout.json")
#         with open(save_path, "w", encoding="utf-8") as f:
#             json.dump(layout, f, ensure_ascii=False, indent=2)

#     if output_format == "json":
#         return {"format": "json", "content": json.dumps(layout, ensure_ascii=False, indent=2)}

#     if not markdown:
#         markdown = layout_to_markdown(layout)
#     return {"format": "markdown", "content": markdown}


# def layout_to_markdown(layout: dict) -> str:
#     blocks = []
#     for page in layout.get("pdf_info", []):
#         page_no = page.get("page_idx", 0) + 1
#         for key in ["para_blocks", "preproc_blocks"]:
#             for block in page.get(key, []):
#                 text = extract_text(block)
#                 if text:
#                     blocks.append((page_no, text))

#     lines = []
#     current_page = None
#     for page_no, text in blocks:
#         if page_no != current_page:
#             current_page = page_no
#             lines.append(f"\n## Page {page_no}\n")
#         lines.append(text)
#     return "\n\n".join(lines).strip()


# def extract_text(block: dict) -> str:
#     parts = []
#     if isinstance(block.get("text"), str):
#         parts.append(block["text"])
#     for line in block.get("lines", []):
#         for span in line.get("spans", []):
#             if span.get("content"):
#                 parts.append(span["content"])
#             if span.get("html"):
#                 parts.append(span["html"])
#     for child in block.get("blocks", []):
#         text = extract_text(child)
#         if text:
#             parts.append(text)
#     return " ".join(str(part) for part in parts).strip()


# def build_source_preview(file_path: str) -> dict:
#     ext = os.path.splitext(file_path)[1].lower()
#     if ext == ".pdf":
#         doc = fitz.open(file_path)
#         images = []
#         for page in doc:
#             pix = page.get_pixmap(matrix=fitz.Matrix(1.2, 1.2))
#             images.append(base64.b64encode(pix.tobytes("png")).decode())
#         page_count = len(doc)
#         doc.close()
#         return {"type": "pdf", "images": images, "page_count": page_count}

#     if ext in [".png", ".jpg", ".jpeg", ".webp", ".bmp"]:
#         with open(file_path, "rb") as f:
#             return {"type": "image", "data": base64.b64encode(f.read()).decode()}

#     try:
#         with open(file_path, "r", encoding="utf-8") as f:
#             return {"type": "text", "content": f.read(12000)}
#     except Exception:
#         return {"type": "file", "content": os.path.basename(file_path)}


# if __name__ == "__main__":
#     import uvicorn

#     uvicorn.run(app, host="0.0.0.0", port=8001)

import base64
import hashlib
import hmac
import io
import json
import mimetypes
import os
import re
import subprocess
import threading
import time
import uuid
import zipfile
import xml.etree.ElementTree as ET
import fitz
import requests
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import HTMLResponse
from minio import Minio
from datetime import datetime, timedelta
import urllib3
from fastapi.responses import FileResponse
from fastapi import HTTPException

from app_2 import (
    MINERU_URL,
    UPLOAD_DIR,
    call_mineru,
    pdf_to_highlighted_images,
    run_pipeline,
)
from text_extract import router as text_extract_router
from no_image_md import router as no_image_md_router

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def load_env_file(path: str = ".env") -> None:
    """从 .env 文件加载环境变量，已有系统环境变量不会被覆盖。"""
    # 读取本地 .env 配置，避免把 MinIO 密钥等敏感信息写死在代码里。
    if not os.path.exists(path) and not os.path.isabs(path):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and not os.environ.get(key):
                os.environ[key] = value


load_env_file()

# 运行时配置：优先读取系统环境变量，其次读取 .env。
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "")
DOCUMENT_CONVERT_URL = os.getenv("DOCUMENT_CONVERT_URL", "http://10.89.16.21:8009/convert")
LIBREOFFICE_BIN = os.getenv("LIBREOFFICE_BIN", "libreoffice")
PARSE_HISTORY_EXPIRE_DAYS = int(os.getenv("PARSE_HISTORY_EXPIRE_DAYS", "7"))
PARSE_MAX_CONCURRENT_JOBS = int(os.getenv("PARSE_MAX_CONCURRENT_JOBS", "2"))
MINERU_MD_API_URL = os.getenv("MINERU_MD_API_URL", "http://127.0.0.1:8010")
MINERU_MD_PARSE_TIMEOUT = int(os.getenv("MINERU_MD_PARSE_TIMEOUT", "900"))
MINERU_MD_POLL_INTERVAL = int(os.getenv("MINERU_MD_POLL_INTERVAL", "2"))
ONLYOFFICE_DOCUMENT_SERVER = os.getenv("ONLYOFFICE_DOCUMENT_SERVER", "").rstrip("/")
ONLYOFFICE_JWT_SECRET = os.getenv("ONLYOFFICE_JWT_SECRET", "")
APP_PUBLIC_BASE_URL = os.getenv("APP_PUBLIC_BASE_URL", "").rstrip("/")
PREVIEW_FILES = {}

# 轻量版后台任务状态保存在内存里；解析完成后的结果会落到 MinIO 历史中。
PARSE_JOBS = {}
PARSE_SEMAPHORE = threading.Semaphore(PARSE_MAX_CONCURRENT_JOBS)

app = FastAPI()
app.include_router(text_extract_router)
app.include_router(no_image_md_router)
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs("output", exist_ok=True)


@app.on_event("startup")
def resume_pending_parse_jobs():
    """服务启动时恢复 MinIO 中未完成的解析任务。"""
    print(f"[app-home-config] MINIO_ENDPOINT exists={bool(MINIO_ENDPOINT)}, length={len(MINIO_ENDPOINT)}")
    print(f"[app-home-config] MINIO_BUCKET exists={bool(MINIO_BUCKET)}, value={MINIO_BUCKET}")
    print(f"[app-home-config] MINERU_MD_API_URL={MINERU_MD_API_URL}")
    recover_pending_parse_jobs()


@app.get("/", response_class=HTMLResponse)
async def index():
    """返回文档解析首页。"""
    with open("templates/home.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/compare-page", response_class=HTMLResponse)
async def compare_page():
    """返回文档对比页面。"""
    with open("templates/index.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/preview-file/{file_id}")
async def preview_file(file_id: str):
    """根据临时预览 ID 返回本地预览文件。"""
    file_path = PREVIEW_FILES.get(file_id)
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="preview file not found")
    return FileResponse(file_path, filename=os.path.basename(file_path))


@app.post("/parse")
async def parse_document(request: Request):
    """同步解析上传文件并直接返回解析结果。"""
    # 同步解析接口保留给兼容场景；当前前端主要走 /parse-jobs 后台解析。
    form = await request.form()
    uploaded = form.get("file")
    output_format = form.get("format") or "markdown"
    if not uploaded:
        return {"error": "missing file"}

    safe_name = os.path.basename(uploaded.filename or "document.pdf")
    allowed_exts = {
        ".pdf", ".docx", ".pptx", ".xlsx", ".csv",
        ".txt", ".md", ".markdown",
    }
    if os.path.splitext(safe_name)[1].lower() not in allowed_exts:
        return {"error": "不支持的文件格式"}

    parse_path = os.path.join(UPLOAD_DIR, f"parse_{safe_name}")
    with open(parse_path, "wb") as f:
        f.write(await uploaded.read())

    mineru_path = parse_path
    parsed = parse_with_mineru_api(parse_path, safe_name)
    return {
        "filename": safe_name,
        "format": parsed["format"],
        "content": parsed["content"],
        "markdown_content": parsed.get("markdown_content", parsed["content"] if parsed["format"] == "markdown" else ""),
        "json_content": parsed.get("json_content", parsed["content"] if parsed["format"] == "json" else ""),
        "content_blocks": parsed.get("content_blocks", []),
        "blocks": parsed.get("content_blocks") or layout_blocks(parsed.get("layout", {})),
        "image_urls": parsed.get("image_urls", {}),
        "task_id": parsed.get("task_id", ""),
        "user_id": parsed.get("user_id", "anonymous"),
        "source": build_source_preview(mineru_path, request),
    }


@app.post("/parse-jobs")
async def create_parse_job(request: Request, background_tasks: BackgroundTasks):
    """创建后台解析任务并返回 job_id 供前端轮询。"""
    # 创建后台解析任务：接口先返回 job_id，前端轮询任务状态。
    # 用户关闭页面后，后台任务仍会继续执行，完成后写入 MinIO 历史。
    form = await request.form()
    uploaded = form.get("file")
    output_format = form.get("format") or "markdown"
    if not uploaded:
        return {"error": "missing file"}

    safe_name = os.path.basename(uploaded.filename or "document.pdf")
    allowed_exts = {
        ".pdf", ".docx", ".pptx", ".xlsx", ".csv",
        ".txt", ".md", ".markdown",
    }
    if os.path.splitext(safe_name)[1].lower() not in allowed_exts:
        return {"error": "不支持的文件格式"}

    client = create_minio_client()
    if not client:
        return {"error": "MinIO 未配置，无法创建可恢复解析任务"}

    job_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
    task_prefix = task_prefix_for(job_id)
    parse_path = os.path.join(UPLOAD_DIR, f"job_{job_id}_{safe_name}")
    with open(parse_path, "wb") as f:
        f.write(await uploaded.read())

    original_object = f"{task_prefix}/original/{safe_name}"
    metadata = {
        "job_id": job_id,
        "task_id": job_id,
        "user_id": "anonymous",
        "filename": safe_name,
        "format": output_format,
        "status": "queued",
        "progress": 0,
        "message": "任务已提交",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "expires_at": (datetime.now() + timedelta(days=PARSE_HISTORY_EXPIRE_DAYS)).isoformat(timespec="seconds"),
        "image_count": 0,
        "image_urls": {},
        "original_object": original_object,
        "markdown_object": f"{task_prefix}/result/result.md",
        "json_object": f"{task_prefix}/result/result.json",
        "error": None,
    }
    upload_file_to_minio(client, original_object, parse_path)
    write_task_metadata(client, metadata)

    PARSE_JOBS[job_id] = {
        **metadata,
        "result": None,
    }
    background_tasks.add_task(run_parse_job, job_id, parse_path, output_format, safe_name, metadata)
    return {
        "job_id": job_id,
        "task_id": job_id,
        "status": "queued",
        "message": "任务已提交，后台解析中",
        "filename": safe_name,
    }


@app.get("/parse-jobs/{job_id}")
async def get_parse_job(job_id: str):
    """查询后台解析任务的当前状态和结果。"""
    job = PARSE_JOBS.get(job_id)
    if not job:
        return {"error": "job not found"}
    return job


@app.get("/parse-history")
async def parse_history():
    """从 MinIO 读取当前用户的历史解析任务列表。"""
    # 历史列表不依赖浏览器内存，而是扫描 MinIO 中的 task.json。
    client = create_minio_client()
    if not client:
        return {"tasks": []}

    tasks = []
    prefix = "mineru/users/anonymous/tasks/"
    for obj in client.list_objects(MINIO_BUCKET, prefix=prefix, recursive=True):
        if not obj.object_name.endswith("/meta/task.json"):
            continue
        try:
            metadata = json.loads(read_minio_text(client, obj.object_name))
            task_id = metadata.get("task_id", "")
            if is_task_expired(metadata):
                if task_id:
                    deleted = delete_task_objects(client, task_id)
                    print(f"历史解析已过期并删除: {task_id}, deleted={deleted}")
                continue
            tasks.append({
                "key": f"history-{task_id}",
                "task_id": task_id,
                "user_id": metadata.get("user_id", "anonymous"),
                "name": metadata.get("filename", "历史解析"),
                "size": 0,
                "status": metadata.get("status", "done"),
                "format": metadata.get("format", "markdown"),
                "progress": metadata.get("progress", 0),
                "message": metadata.get("message", ""),
                "error": metadata.get("error"),
                "created_at": metadata.get("created_at", ""),
                "expires_at": metadata.get("expires_at", ""),
                "image_count": metadata.get("image_count", 0),
                "history": True,
            })
        except Exception as e:
            print(f"读取历史记录失败: {obj.object_name} - {e}")

    tasks.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return {"tasks": tasks}


@app.get("/parse-history/{task_id}")
async def parse_history_detail(task_id: str):
    """读取某个历史解析任务的完整结果。"""
    # 根据任务 ID 读取 MinIO 中的结果文件，并恢复成前端需要的结构。
    safe_task_id = os.path.basename(task_id)
    client = create_minio_client()
    if not client:
        return {"error": "MinIO 未配置"}

    task_prefix = f"mineru/users/anonymous/tasks/{safe_task_id}"
    try:
        metadata = json.loads(read_minio_text(client, f"{task_prefix}/meta/task.json"))
        status = metadata.get("status", "done")
        if status != "done":
            return {
                "filename": metadata.get("filename", "历史解析"),
                "format": metadata.get("format", "markdown"),
                "content": "",
                "markdown_content": "",
                "json_content": "",
                "content_blocks": [],
                "blocks": [],
                "image_urls": metadata.get("image_urls", {}),
                "task_id": safe_task_id,
                "user_id": metadata.get("user_id", "anonymous"),
                "status": status,
                "progress": metadata.get("progress", 0),
                "message": metadata.get("message", ""),
                "error": metadata.get("error"),
                "source": {"type": "file", "content": metadata.get("message", "任务尚未完成")},
            }
        markdown_object = metadata.get("markdown_object") or f"{task_prefix}/result/result.md"
        json_object = metadata.get("json_object") or f"{task_prefix}/result/result.json"
        original_object = metadata.get("original_object") or find_first_minio_object(client, f"{task_prefix}/original/")
        markdown = read_minio_text(client, markdown_object)
        json_content = read_minio_text(client, json_object)
        source = {"type": "file", "content": metadata.get("filename", "历史解析")}
        if original_object:
            original_path = download_minio_object_to_uploads(client, original_object)
            source = build_source_preview(original_path)
    except Exception as e:
        return {"error": f"读取历史解析失败: {e}"}

    result_format = metadata.get("format", "markdown")
    result_content = json_content if result_format == "json" else markdown
    return {
        "filename": metadata.get("filename", "历史解析"),
        "format": result_format,
        "content": result_content,
        "markdown_content": markdown,
        "json_content": json_content,
        "content_blocks": [],
        "blocks": [],
        "image_urls": metadata.get("image_urls", {}),
        "task_id": safe_task_id,
        "user_id": metadata.get("user_id", "anonymous"),
        "status": "done",
        "progress": 100,
        "message": metadata.get("message", "解析完成"),
        "source": source,
    }


@app.delete("/parse-history/{task_id}")
async def delete_parse_history(task_id: str):
    """删除某个历史解析任务及其 MinIO 文件。"""
    # 删除历史时会删除该 task_id 前缀下的原文件、图片、结果和元数据。
    safe_task_id = os.path.basename(task_id)
    client = create_minio_client()
    if not client:
        return {"error": "MinIO 未配置"}

    try:
        deleted = delete_task_objects(client, safe_task_id)
    except Exception as e:
        return {"error": f"删除历史解析失败: {e}"}

    return {"deleted": deleted}
@app.get("/layout/{base_name}")
async def get_layout(base_name: str):
    """读取本地 output 目录中的 layout JSON 调试文件。"""
    import glob
    files = glob.glob("output/*_parse_layout.json")
    print(f"  output目录中的文件: {[os.path.basename(f) for f in files]}")
    print(f"  请求 layout: {base_name}")
    layout_path = os.path.join("output", f"{base_name}_parse_layout.json")
    print(f"  查找路径: {layout_path}")
    print(f"  文件存在: {os.path.exists(layout_path)}")
    if os.path.exists(layout_path):
        return FileResponse(layout_path, media_type="application/json")
    raise HTTPException(status_code=404, detail="layout not found")

@app.post("/compare")
async def compare(request: Request):
    """执行文档对比并返回差异和高亮图片。"""
    form = await request.form()
    fb = form.get("file_before")
    fa = form.get("file_after")
    pb = os.path.join(UPLOAD_DIR, "before.pdf")
    pa = os.path.join(UPLOAD_DIR, "after.pdf")
    with open(pb, "wb") as f:
        f.write(await fb.read())
    with open(pa, "wb") as f:
        f.write(await fa.read())

    lb = call_mineru(pb)
    la = call_mineru(pa)
    diffs = run_pipeline(lb, la, pb, pa)
    return {
        "diffs": diffs,
        "before_images": pdf_to_highlighted_images(pb, diffs, "before"),
        "after_images": pdf_to_highlighted_images(pa, diffs, "after"),
    }


def prepare_file_for_mineru(file_path: str) -> str:
    """判断文件是否可直接送 MinerU，必要时先转换成 PDF。"""
    # MinerU 原生只处理 PDF、图片和部分 Office 格式；旧格式先统一转 PDF。
    ext = os.path.splitext(file_path)[1].lower()
    mineru_exts = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".docx", ".pptx", ".xlsx"}
    convert_exts = {".doc", ".rtf", ".xls", ".csv", ".ppt", ".html", ".htm"}
    if ext in mineru_exts:
        return file_path
    if ext in convert_exts:
        return convert_file_to_pdf(file_path)
    raise RuntimeError(f"不支持的文件格式: {ext or 'unknown'}")


def parse_text_document(
    file_path: str,
    output_format: str = "markdown",
    original_filename: str | None = None,
    metadata: dict | None = None,
) -> dict:
    """读取 TXT 原文并生成与 MinerU 解析结果一致的返回结构。"""
    # TXT 文件不调用 MinerU，直接把原文保存成 result.md/result.json。
    # 这样它也能进入左侧历史记录，并支持刷新后恢复。
    original_filename = original_filename or os.path.basename(file_path)
    text = read_text_file(file_path)
    json_content = json.dumps(
        {
            "type": "text",
            "filename": original_filename,
            "content": text,
        },
        ensure_ascii=False,
        indent=2,
    )
    metadata = dict(metadata or {})
    user_id = metadata.get("user_id", "anonymous")
    task_id = metadata.get("task_id") or datetime.now().strftime("%Y%m%d_%H%M%S_") + str(uuid.uuid4())[:8]
    task_prefix = task_prefix_for(task_id, user_id)
    minio_client = create_minio_client()
    original_object = metadata.get("original_object") or f"{task_prefix}/original/{original_filename}"

    if minio_client:
        if not metadata.get("original_object"):
            upload_file_to_minio(minio_client, original_object, file_path)
        md_object = metadata.get("markdown_object") or f"{task_prefix}/result/result.md"
        json_object = metadata.get("json_object") or f"{task_prefix}/result/result.json"
        upload_bytes_to_minio(
            minio_client,
            md_object,
            text.encode("utf-8"),
            "text/plain; charset=utf-8",
        )
        upload_bytes_to_minio(
            minio_client,
            json_object,
            json_content.encode("utf-8"),
            "application/json; charset=utf-8",
        )
        metadata.update({
            "task_id": task_id,
            "user_id": user_id,
            "filename": original_filename,
            "format": "text",
            "status": "done",
            "progress": 100,
            "message": "解析完成",
            "created_at": metadata.get("created_at") or datetime.now().isoformat(timespec="seconds"),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "expires_at": (datetime.now() + timedelta(days=PARSE_HISTORY_EXPIRE_DAYS)).isoformat(timespec="seconds"),
            "image_count": 0,
            "image_urls": {},
            "original_object": original_object,
            "markdown_object": md_object,
            "json_object": json_object,
            "error": None,
        })
        write_task_metadata(minio_client, metadata)

    if output_format == "json":
        return {
            "format": "json",
            "content": json_content,
            "markdown_content": text,
            "json_content": json_content,
            "content_blocks": [],
            "image_urls": {},
            "layout": {},
            "task_id": task_id,
            "user_id": user_id,
        }
    return {
        "format": "text",
        "content": text,
        "markdown_content": text,
        "json_content": json_content,
        "content_blocks": [],
        "image_urls": {},
        "layout": {},
        "task_id": task_id,
        "user_id": user_id,
    }


def parse_with_mineru_api(
    file_path: str,
    original_filename: str,
    metadata: dict | None = None,
) -> dict:
    """调用独立 MinerU Markdown API，等待完成后转换成 app_home 前端需要的结构。"""
    metadata = dict(metadata or {})
    user_id = metadata.get("user_id", "anonymous")
    task_id = submit_mineru_md_task(file_path, original_filename, user_id)
    if metadata.get("job_id") or metadata.get("task_id"):
        update_parse_job_state(
            metadata.get("job_id") or metadata.get("task_id"),
            metadata,
            "running",
            45,
            f"已提交 MinerU 解析任务: {task_id}",
        )
    result = wait_mineru_md_done(task_id)
    return build_result_from_mineru_api_result(result, metadata)


def submit_mineru_md_task(file_path: str, filename: str, user_id: str) -> str:
    """提交文件到独立 /parse-md 接口并返回 task_id。"""
    with open(file_path, "rb") as f:
        response = requests.post(
            f"{MINERU_MD_API_URL.rstrip('/')}/parse-md",
            files={"file": (filename, f)},
            data={"user_id": user_id},
            timeout=60,
        )
    response.raise_for_status()
    data = response.json()
    task_id = data.get("task_id")
    if not task_id:
        raise RuntimeError(f"MinerU API did not return task_id: {data}")
    return task_id


def wait_mineru_md_done(task_id: str) -> dict:
    """轮询独立 /parse-md/{task_id}，直到完成或失败。"""
    started = time.time()
    while time.time() - started < MINERU_MD_PARSE_TIMEOUT:
        response = requests.get(f"{MINERU_MD_API_URL.rstrip('/')}/parse-md/{task_id}", timeout=30)
        response.raise_for_status()
        data = response.json()
        status = data.get("status")
        if status == "done":
            return data
        if status == "failed":
            raise RuntimeError(data.get("error") or f"MinerU API parse failed: {task_id}")
        time.sleep(MINERU_MD_POLL_INTERVAL)
    raise TimeoutError(f"MinerU API parse timeout: {task_id}")


def build_result_from_mineru_api_result(result: dict, metadata: dict | None = None) -> dict:
    """下载独立解析接口产物，并转换成 app_home 的历史/预览结果结构。"""
    metadata = dict(metadata or {})
    markdown_url = result.get("markdown_url")
    print(f"[app-home] markdown_url={markdown_url or '<empty>'}")
    markdown = download_text_url(markdown_url, "markdown_url")
    print(f"[app-home] markdown length={len(markdown)}")
    if not markdown.strip():
        raise RuntimeError(f"Downloaded markdown content is empty: {markdown_url}")
    layout = download_json_url(result.get("json_url"))
    json_content = json.dumps(layout, ensure_ascii=False, indent=2)
    image_urls = result.get("image_urls", {}) or {}
    content_blocks = merge_layout_content_blocks(layout_blocks(layout), [], image_urls)

    client = create_minio_client()
    app_task_id = metadata.get("task_id") or metadata.get("job_id") or result.get("task_id")
    if client and app_task_id:
        metadata.update({
            "task_id": app_task_id,
            "user_id": metadata.get("user_id", result.get("user_id", "anonymous")),
            "filename": metadata.get("filename", result.get("filename", "document")),
            "format": "markdown",
            "status": "done",
            "progress": 100,
            "message": "解析完成",
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "image_count": result.get("image_count", 0),
            "skipped_image_count": result.get("skipped_image_count", 0),
            "image_urls": image_urls,
            "original_object": result.get("original_object") or result.get("parse_file_object") or metadata.get("original_object"),
            "markdown_object": result.get("markdown_object") or metadata.get("markdown_object"),
            "json_object": result.get("json_object") or metadata.get("json_object"),
            "mineru_task_id": result.get("task_id"),
            "mineru_markdown_url": result.get("markdown_url"),
            "mineru_json_url": result.get("json_url"),
            "mineru_parse_file_url": result.get("parse_file_url"),
            "error": None,
        })
        write_task_metadata(client, metadata)

    return {
        "task_id": app_task_id or result.get("task_id", ""),
        "user_id": metadata.get("user_id", result.get("user_id", "anonymous")),
        "format": "markdown",
        "content": markdown,
        "markdown_content": markdown,
        "json_content": json_content,
        "content_blocks": content_blocks,
        "image_urls": image_urls,
        "layout": layout,
        "mineru_task_id": result.get("task_id"),
    }


def download_text_url(url: str, field_name: str = "url") -> str:
    """下载文本 URL 并按 UTF-8 解码。"""
    if not url:
        raise RuntimeError(f"{field_name} is empty")
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    return response.content.decode("utf-8", errors="replace")


def download_json_url(url: str) -> dict:
    """下载 JSON URL。"""
    if not url:
        return {}
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    return response.json()


def read_text_file(file_path: str) -> str:
    """按常见编码读取文本文件内容。"""
    # 兼容常见中文文本编码，避免 GB18030 的 TXT 在 Windows 上读取失败。
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            with open(file_path, "r", encoding=encoding) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def run_parse_job(
    job_id: str,
    parse_path: str,
    output_format: str,
    safe_name: str,
    metadata: dict | None = None,
) -> None:
    """后台执行解析任务并更新任务状态。"""
    # 后台执行真正的解析流程；信号量用于限制同时解析的任务数量。
    job = PARSE_JOBS.get(job_id)
    if not job:
        job = {
            "job_id": job_id,
            "task_id": job_id,
            "filename": safe_name,
            "format": output_format,
            "result": None,
            "error": None,
        }
        PARSE_JOBS[job_id] = job
    metadata = dict(metadata or job)
    update_parse_job_state(job_id, metadata, "queued", 5, "等待空闲解析通道")
    with PARSE_SEMAPHORE:
        try:
            update_parse_job_state(job_id, metadata, "running", 15, "正在准备文件")
            mineru_path = parse_path
            update_parse_job_state(job_id, metadata, "running", 35, "正在调用 MinerU 解析接口")
            parsed = parse_with_mineru_api(parse_path, safe_name, metadata)

            job.update(status="running", progress=85, message="正在生成源文件预览")
            result = {
                "filename": safe_name,
                "format": parsed["format"],
                "content": parsed["content"],
                "markdown_content": parsed.get("markdown_content", parsed["content"] if parsed["format"] == "markdown" else ""),
                "json_content": parsed.get("json_content", parsed["content"] if parsed["format"] == "json" else ""),
                "content_blocks": parsed.get("content_blocks", []),
                "blocks": parsed.get("content_blocks") or layout_blocks(parsed.get("layout", {})),
                "image_urls": parsed.get("image_urls", {}),
                "task_id": parsed.get("task_id", ""),
                "user_id": parsed.get("user_id", "anonymous"),
                "source": build_source_preview(mineru_path),
            }
            job.update(status="done", progress=100, message="解析完成", result=result, error=None)
            update_parse_job_state(job_id, metadata, "done", 100, "解析完成", error=None)
        except Exception as e:
            print(f"后台解析失败: job_id={job_id}, file={safe_name}, error={e}")
            job.update(status="failed", progress=100, message="解析失败", error=str(e))
            update_parse_job_state(job_id, metadata, "failed", 100, "解析失败", error=str(e))


def convert_file_to_pdf(file_path: str) -> str:
    """把不被 MinerU 原生支持的文件转换成 PDF。"""
    # 先走公司内部转换服务；失败时再用本机 LibreOffice 兜底转换。
    api_error = ""
    if DOCUMENT_CONVERT_URL:
        try:
            return convert_file_to_pdf_by_api(file_path)
        except Exception as e:
            api_error = str(e)
            print(f"内部转换服务失败，尝试 LibreOffice 兜底: {api_error}")
    try:
        return convert_file_to_pdf_by_libreoffice(file_path)
    except Exception as e:
        if api_error:
            raise RuntimeError(f"文档转 PDF 失败: 内部转换服务: {api_error}; LibreOffice: {e}")
        raise


def convert_file_to_pdf_by_api(file_path: str) -> str:
    """调用内部转换服务把文件转换为 PDF。"""
    # 内部转换服务应直接返回 PDF 二进制内容。
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    pdf_path = os.path.join(UPLOAD_DIR, f"converted_{uuid.uuid4().hex[:8]}_{base_name}.pdf")
    with open(file_path, "rb") as f:
        files = {"file": (os.path.basename(file_path), f)}
        response = requests.post(DOCUMENT_CONVERT_URL, files=files, timeout=300)
    if response.status_code != 200:
        detail = response.text[:500] if response.text else ""
        raise RuntimeError(f"文档转 PDF 失败: {response.status_code} {detail}")
    if not response.content.startswith(b"%PDF"):
        detail = response.text[:500] if response.text else "转换服务未返回 PDF 内容"
        raise RuntimeError(f"文档转 PDF 失败: {detail}")
    with open(pdf_path, "wb") as f:
        f.write(response.content)
    return pdf_path


def convert_file_to_pdf_by_libreoffice(file_path: str) -> str:
    """使用本机 LibreOffice headless 模式把文件转换为 PDF。"""
    # LibreOffice 会按原文件名生成 PDF，这里处理同名文件冲突和最终路径。
    if not LIBREOFFICE_BIN:
        raise RuntimeError("未配置 LibreOffice 命令")
    output_dir = UPLOAD_DIR
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    expected_pdf = os.path.join(output_dir, f"{base_name}.pdf")
    if os.path.exists(expected_pdf):
        expected_pdf = os.path.join(output_dir, f"{base_name}_{uuid.uuid4().hex[:8]}.pdf")

    command = [
        LIBREOFFICE_BIN,
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        output_dir,
        file_path,
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or f"命令返回 {result.returncode}")

    generated_pdf = os.path.join(output_dir, f"{base_name}.pdf")
    if not os.path.exists(generated_pdf):
        raise RuntimeError("未生成 PDF 文件")
    if generated_pdf != expected_pdf and os.path.exists(expected_pdf):
        os.remove(expected_pdf)
    if generated_pdf != expected_pdf:
        os.replace(generated_pdf, expected_pdf)
    return expected_pdf


def call_mineru_document(
    file_path: str,
    output_format: str = "markdown",
    original_file_path: str | None = None,
    original_filename: str | None = None,
    metadata: dict | None = None,
) -> dict:
    """调用 MinerU 解析文档，并把结果、图片和元数据保存到 MinIO。"""
    # 调用 MinerU 并解析返回的 ZIP：里面通常包含 layout/content_list/md/images。
    # 同时负责把图片、结果文件和任务元数据上传到 MinIO。
    original_file_path = original_file_path or file_path
    original_filename = original_filename or os.path.basename(original_file_path)
    metadata = dict(metadata or {})
    with open(file_path, "rb") as f:
        files = [("files", (os.path.basename(file_path), f))]
        data = {
            "backend": "vlm-auto-engine",
            "response_format_zip": True,
            "return_middle_json": True,
            "return_model_output": False,
            "return_content_list": True,
            "return_images": True,
        }
        resp = requests.post(MINERU_URL, files=files, data=data, timeout=600)

    if resp.status_code != 200:
        detail = resp.text[:500] if resp.text else ""
        raise RuntimeError(f"MinerU parse failed: {resp.status_code} {detail}")

    layout = {}
    markdown = ""
    content_list = []
    images = {}
    image_urls = {}
    user_id = metadata.get("user_id", "anonymous")
    task_id = metadata.get("task_id") or datetime.now().strftime("%Y%m%d_%H%M%S_") + str(uuid.uuid4())[:8]
    task_prefix = task_prefix_for(task_id, user_id)
    minio_client = create_minio_client()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        # 兼容不同 MinerU 版本的文件名：layout 可能叫 middle.json 或 layout.json。
        for name in zf.namelist():
            lower = name.lower()
            if lower.endswith(("middle.json", "layout.json")) and not layout:
                layout = json.loads(zf.read(name).decode("utf-8"))
            elif lower.endswith("content_list.json") and not content_list:
                content_list = json.loads(zf.read(name).decode("utf-8"))
            elif lower.endswith((".md", ".markdown")) and not markdown:
                markdown = zf.read(name).decode("utf-8", errors="replace")
            elif 'images/' in name and not name.endswith('/'):
                img_name = name.split('/')[-1]
                images[img_name] = zf.read(name)
                print(f"  提取图片: {img_name} ({len(images[img_name])} bytes)")
    print(f"Extracted {len(images)} images")
    original_object = metadata.get("original_object") or f"{task_prefix}/original/{original_filename}"
    if minio_client:
        # 历史中保存用户上传的原始文件，不保存转换后的临时 PDF。
        if not metadata.get("original_object"):
            upload_file_to_minio(
                minio_client,
                original_object,
                original_file_path,
            )
    if images and minio_client:
        print(f"开始上传到 MinIO, task_id={task_id}")
        for img_name, img_data in images.items():
            object_name = f"{task_prefix}/images/{img_name}"
            try:
                presigned_url = upload_bytes_to_minio(minio_client, object_name, img_data)
                # Markdown 里可能引用 images/a.jpg，也可能只引用 a.jpg，两种都映射。
                image_urls[img_name] = presigned_url
                image_urls[f"images/{img_name}"] = presigned_url
                print(f"  上传成功: {object_name}")
            except Exception as e:
                print(f"  MinIO 上传失败: {img_name} - {e}")
    # -------------------------------

    if layout:
        base_name = os.path.basename(original_filename).rsplit(".", 1)[0]
        # Remove the parse_ prefix from uploaded file names.
        if base_name.startswith("parse_"):
            base_name = base_name[6:]
        save_path = os.path.join("output", f"{base_name}_parse_layout.json")
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(layout, f, ensure_ascii=False, indent=2)

    if not markdown:
        # 少数情况下 MinerU 不返回 md 文件，用 layout 文本生成一个兜底 Markdown。
        markdown = layout_to_markdown(layout)
        # Details expansion is handled in the frontend so chart data can stay collapsed.
    markdown = replace_image_refs(markdown, image_urls)
    for img_name in images:
        if img_name in markdown:
            print(f"  找到引用: {img_name}")
        else:
            print(f"  未找到引用: {img_name}")
    
    refs = re.findall(r'!\[.*?\]\(([^)]+)\)', markdown)
    print(f"  Markdown图片引用数量: {len(refs)}")
    export_layout = replace_image_refs_in_json(layout, image_urls)
    json_content = json.dumps(export_layout, ensure_ascii=False, indent=2)
    content_blocks = merge_layout_content_blocks(layout_blocks(layout), content_list, image_urls)
    if minio_client:
        # 导出的 Markdown/JSON 使用已经替换过的 MinIO 图片 URL。
        md_object = metadata.get("markdown_object") or f"{task_prefix}/result/result.md"
        json_object = metadata.get("json_object") or f"{task_prefix}/result/result.json"
        upload_bytes_to_minio(
            minio_client,
            md_object,
            markdown.encode("utf-8"),
            "text/markdown; charset=utf-8",
        )
        print(f"  上传成功: {md_object}")
        upload_bytes_to_minio(
            minio_client,
            json_object,
            json_content.encode("utf-8"),
            "application/json; charset=utf-8",
        )
        print(f"  上传成功: {json_object}")
        metadata.update({
            "task_id": task_id,
            "user_id": user_id,
            "filename": original_filename,
            "format": output_format,
            "status": "done",
            "progress": 100,
            "message": "解析完成",
            "created_at": metadata.get("created_at") or datetime.now().isoformat(timespec="seconds"),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "expires_at": (datetime.now() + timedelta(days=PARSE_HISTORY_EXPIRE_DAYS)).isoformat(timespec="seconds"),
            "image_count": len(images),
            "image_urls": image_urls,
            "original_object": original_object,
            "markdown_object": md_object,
            "json_object": json_object,
            "error": None,
        })
        write_task_metadata(minio_client, metadata)
        print(f"  上传成功: {task_meta_object(task_id, user_id)}")
    if output_format == "json":
        return {
            "format": "json",
            "content": json_content,
            "markdown_content": markdown,
            "json_content": json_content,
            "content_blocks": content_blocks,
            "image_urls": image_urls,
            "layout": layout,
            "task_id": task_id,
            "user_id": user_id,
        }
    return {
        "format": "markdown",
        "content": markdown,
        "markdown_content": markdown,
        "json_content": json_content,
        "content_blocks": content_blocks,
        "image_urls": image_urls,
        "layout": layout,
        "task_id": task_id,
        "user_id": user_id,
    }


def layout_blocks(layout: dict) -> list:
    """从 MinerU layout JSON 中提取可定位的内容块。"""
    blocks = []
    seen = set()
    for page in layout.get("pdf_info", []):
        page_no = page.get("page_idx", 0)
        for block in page_layout_blocks(page):
            collect_layout_block(block, page_no, blocks, seen)
    blocks.sort(key=lambda item: (item["page"], item["bbox"][1], item["bbox"][0]))
    return blocks


def merge_layout_content_blocks(layout_items: list, content_list: list, image_urls: dict) -> list:
    """把 layout 坐标块和 content_list 内容合并成前端可点击的内容块。"""
    if not layout_items:
        return []

    content_items = content_list if isinstance(content_list, list) else []
    merged = []
    content_cursor = 0
    for index, layout_item in enumerate(layout_items):
        content, content_cursor = match_content_item(layout_item, content_items, content_cursor)
        item_type = content.get("type") or layout_item.get("type") or "text"
        image_path = content.get("img_path") or content.get("image_path") or content.get("image")
        image_url = resolve_image_url(image_path, image_urls)
        raw_text = (
            content.get("text")
            or content.get("content")
            or content.get("caption")
            or layout_item.get("text")
            or ""
        )
        text = replace_image_refs(raw_text, image_urls)
        html = replace_image_refs(content.get("html") or content.get("table_body") or "", image_urls)
        markdown = replace_image_refs(content.get("markdown") or "", image_urls)
        merged.append({
            "id": index,
            "page": layout_item.get("page"),
            "bbox": layout_item.get("bbox"),
            "type": item_type,
            "text": text,
            "html": html,
            "image": image_url,
            "markdown": markdown,
        })
    return merged


def resolve_image_url(image_path: str, image_urls: dict) -> str:
    """根据 MinerU 图片路径查找对应的 MinIO 访问 URL。"""
    if not image_path:
        return ""
    image_path = str(image_path)
    if image_path.startswith(("http://", "https://", "data:")):
        return image_path
    image_name = os.path.basename(image_path)
    return image_urls.get(image_path) or image_urls.get(image_name) or ""


def replace_image_refs(value: str, image_urls: dict) -> str:
    """替换 Markdown/HTML 字符串中的本地图片路径为 MinIO URL。"""
    if not value or not image_urls:
        return value or ""
    result = str(value)
    for path, url in sorted(image_urls.items(), key=lambda item: len(item[0]), reverse=True):
        if path.startswith(("http://", "https://", "data:")):
            continue
        name = os.path.basename(path)
        for ref in {path, name, f"./{path}", f"./{name}"}:
            escaped = re.escape(ref)
            result = re.sub(rf'src="{escaped}"', f'src="{url}"', result)
            result = re.sub(rf"src='{escaped}'", f"src='{url}'", result)
            result = re.sub(rf"\]\({escaped}\)", f"]({url})", result)
    return result


def replace_image_refs_in_json(value, image_urls: dict):
    """递归替换 JSON 结构中出现的图片路径。"""
    if not image_urls:
        return value
    if isinstance(value, dict):
        return {key: replace_image_refs_in_json(item, image_urls) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_image_refs_in_json(item, image_urls) for item in value]
    if isinstance(value, str):
        return replace_image_refs(value, image_urls)
    return value


def create_minio_client():
    """创建 MinIO 客户端；配置不完整时返回 None。"""
    if not all([MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY, MINIO_BUCKET]):
        return None
    return Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=False,
        cert_check=False,
    )


def task_prefix_for(task_id: str, user_id: str = "anonymous") -> str:
    """生成某个任务在 MinIO 中的对象前缀。"""
    safe_task_id = os.path.basename(task_id)
    safe_user_id = os.path.basename(user_id or "anonymous")
    return f"mineru/users/{safe_user_id}/tasks/{safe_task_id}"


def task_meta_object(task_id: str, user_id: str = "anonymous") -> str:
    """生成某个任务的 MinIO 元数据对象路径。"""
    return f"{task_prefix_for(task_id, user_id)}/meta/task.json"


def write_task_metadata(client, metadata: dict) -> None:
    """把任务元数据写入 MinIO。"""
    if not client:
        return
    task_id = metadata.get("task_id") or metadata.get("job_id")
    user_id = metadata.get("user_id", "anonymous")
    upload_bytes_to_minio(
        client,
        task_meta_object(task_id, user_id),
        json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8"),
        "application/json; charset=utf-8",
    )


def update_parse_job_state(
    job_id: str,
    metadata: dict,
    status: str,
    progress: int,
    message: str,
    error: str | None = None,
) -> None:
    """同时更新内存任务状态和 MinIO 任务元数据。"""
    metadata.update({
        "job_id": job_id,
        "task_id": metadata.get("task_id") or job_id,
        "status": status,
        "progress": progress,
        "message": message,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "error": error,
    })
    job = PARSE_JOBS.setdefault(job_id, {})
    job.update(metadata)
    client = create_minio_client()
    if client:
        write_task_metadata(client, metadata)


def recover_pending_parse_jobs() -> None:
    """扫描 MinIO 中 queued/running 任务，并在服务启动后重新提交后台解析。"""
    client = create_minio_client()
    if not client:
        return
    prefix = "mineru/users/anonymous/tasks/"
    recovered = 0
    for obj in client.list_objects(MINIO_BUCKET, prefix=prefix, recursive=True):
        if not obj.object_name.endswith("/meta/task.json"):
            continue
        try:
            metadata = json.loads(read_minio_text(client, obj.object_name))
            if is_task_expired(metadata):
                continue
            if metadata.get("status") not in {"queued", "running"}:
                continue
            task_id = metadata.get("task_id") or metadata.get("job_id")
            original_object = metadata.get("original_object")
            filename = metadata.get("filename", "document.pdf")
            if not task_id or not original_object:
                continue
            parse_path = download_minio_object_to_uploads(client, original_object)
            metadata["status"] = "queued"
            metadata["progress"] = 0
            metadata["message"] = "服务重启后已恢复任务"
            write_task_metadata(client, metadata)
            PARSE_JOBS[task_id] = {
                **metadata,
                "job_id": task_id,
                "result": None,
                "error": None,
            }
            thread = threading.Thread(
                target=run_parse_job,
                args=(task_id, parse_path, metadata.get("format", "markdown"), filename, metadata),
                daemon=True,
            )
            thread.start()
            recovered += 1
        except Exception as e:
            print(f"恢复历史解析任务失败: {obj.object_name} - {e}")
    if recovered:
        print(f"已恢复未完成解析任务: {recovered}")


def upload_bytes_to_minio(client, object_name: str, data: bytes, content_type: str | None = None) -> str:
    """上传字节内容到 MinIO，并返回预签名访问 URL。"""
    if client is None:
        return ""
    file_obj = io.BytesIO(data)
    length = len(data)
    if content_type:
        client.put_object(
            MINIO_BUCKET,
            object_name,
            file_obj,
            length,
            content_type=content_type,
        )
    else:
        client.put_object(
            MINIO_BUCKET,
            object_name,
            file_obj,
            length,
        )
    return client.presigned_get_object(
        MINIO_BUCKET,
        object_name,
        expires=timedelta(days=7),
    )


def upload_file_to_minio(client, object_name: str, file_path: str) -> str:
    """上传本地文件到 MinIO。"""
    with open(file_path, "rb") as f:
        data = f.read()
    content_type = mimetypes.guess_type(file_path)[0]
    return upload_bytes_to_minio(client, object_name, data, content_type)


def is_task_expired(metadata: dict) -> bool:
    """判断历史任务是否已经超过有效期。"""
    expires_at = metadata.get("expires_at")
    if expires_at:
        try:
            return datetime.fromisoformat(expires_at) <= datetime.now()
        except ValueError:
            pass

    created_at = metadata.get("created_at")
    if not created_at:
        return False
    try:
        created = datetime.fromisoformat(created_at)
    except ValueError:
        return False
    return created + timedelta(days=PARSE_HISTORY_EXPIRE_DAYS) <= datetime.now()


def delete_task_objects(client, task_id: str) -> int:
    """删除某个任务前缀下的所有 MinIO 对象。"""
    safe_task_id = os.path.basename(task_id)
    prefix = f"mineru/users/anonymous/tasks/{safe_task_id}/"
    deleted = 0
    for obj in list(client.list_objects(MINIO_BUCKET, prefix=prefix, recursive=True)):
        client.remove_object(MINIO_BUCKET, obj.object_name)
        deleted += 1
    return deleted


def read_minio_text(client, object_name: str) -> str:
    """读取 MinIO 文本对象并按 UTF-8 解码。"""
    response = client.get_object(MINIO_BUCKET, object_name)
    try:
        return response.read().decode("utf-8", errors="replace")
    finally:
        response.close()
        response.release_conn()


def find_first_minio_object(client, prefix: str) -> str:
    """查找某个 MinIO 前缀下的第一个对象名。"""
    for obj in client.list_objects(MINIO_BUCKET, prefix=prefix, recursive=True):
        return obj.object_name
    return ""


def download_minio_object_to_uploads(client, object_name: str) -> str:
    """把 MinIO 对象下载到本地 uploads 目录，用于源文件预览。"""
    filename = os.path.basename(object_name) or "history_file"
    file_path = os.path.join(UPLOAD_DIR, f"history_{uuid.uuid4().hex[:8]}_{filename}")
    response = client.get_object(MINIO_BUCKET, object_name)
    try:
        with open(file_path, "wb") as f:
            for chunk in response.stream(1024 * 1024):
                f.write(chunk)
    finally:
        response.close()
        response.release_conn()
    return file_path


def match_content_item(layout_item: dict, content_items: list, cursor: int) -> tuple:
    """在 content_list 中为 layout 块匹配最接近的内容项。"""
    if cursor >= len(content_items):
        return {}, cursor

    layout_text = normalize_match_text(layout_item.get("text", ""))
    best_index = -1
    best_score = 0
    search_end = min(len(content_items), cursor + 8)

    for index in range(cursor, search_end):
        content = content_items[index]
        if not isinstance(content, dict):
            continue
        content_text = normalize_match_text(content_text_value(content))
        score = text_match_score(layout_text, content_text)
        if score > best_score:
            best_score = score
            best_index = index

    if best_index >= 0 and best_score >= 0.45:
        return content_items[best_index], best_index + 1

    return {}, cursor


def content_text_value(content: dict) -> str:
    """提取 content_list 项中可用于文本匹配的内容。"""
    return " ".join(str(value) for value in [
        content.get("text"),
        content.get("content"),
        content.get("caption"),
        content.get("html"),
        content.get("markdown"),
    ] if value)


def text_match_score(left: str, right: str) -> float:
    """计算两个归一化文本的相似度分数。"""
    if not left or not right:
        return 0.0
    if left in right or right in left:
        return min(len(left), len(right)) / max(len(left), len(right))
    prefix = left[: min(40, len(left))]
    if len(prefix) >= 8 and prefix in right:
        return len(prefix) / max(len(left), len(right))
    left_tokens = set(left[i:i + 2] for i in range(max(0, len(left) - 1)))
    right_tokens = set(right[i:i + 2] for i in range(max(0, len(right) - 1)))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def normalize_match_text(text: str) -> str:
    """把文本归一化为只包含字母数字的小写字符串。"""
    return "".join(ch.lower() for ch in str(text or "") if ch.isalnum())


def page_layout_blocks(page: dict) -> list:
    """获取单页中可遍历的版面块列表。"""
    para_blocks = page.get("para_blocks") or []
    if para_blocks:
        return para_blocks
    return page.get("preproc_blocks") or []


def collect_layout_block(block: dict, page_no: int, blocks: list, seen: set):
    """递归收集带 bbox 和文本的 layout 块。"""
    bbox = block.get("bbox")
    text = extract_text(block)
    if bbox and len(bbox) == 4 and text:
        identity = (page_no, tuple(bbox), text[:80])
        if identity not in seen:
            seen.add(identity)
            blocks.append({
                "page": page_no,
                "bbox": bbox,
                "type": block.get("type", "text"),
                "text": text,
            })
        return
    for child in block.get("blocks", []):
        collect_layout_block(child, page_no, blocks, seen)


def layout_to_markdown(layout: dict) -> str:
    """把 MinerU layout JSON 兜底转换为简单 Markdown 文本。"""
    blocks = []
    for page in layout.get("pdf_info", []):
        page_no = page.get("page_idx", 0) + 1
        for block in page_layout_blocks(page):
            text = extract_text(block)
            if text:
                blocks.append((page_no, text))

    lines = []
    current_page = None
    for page_no, text in blocks:
        if page_no != current_page:
            current_page = page_no
            lines.append(f"\n## Page {page_no}\n")
        lines.append(text)
    return "\n\n".join(lines).strip()


def extract_text(block: dict) -> str:
    """从 layout 块及其子块中提取纯文本。"""
    parts = []
    if isinstance(block.get("text"), str):
        parts.append(block["text"])
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            if span.get("content"):
                parts.append(span["content"])
            if span.get("html"):
                parts.append(span["html"])
    for child in block.get("blocks", []):
        text = extract_text(child)
        if text:
            parts.append(text)
    return " ".join(str(part) for part in parts).strip()


def build_source_preview(file_path: str, request: Request = None) -> dict:
    """根据文件类型生成左侧源文件预览数据。"""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        return build_pdf_preview(file_path)

    if ext in [".png", ".jpg", ".jpeg", ".webp", ".bmp"]:
        with open(file_path, "rb") as f:
            return {"type": "image", "data": base64.b64encode(f.read()).decode()}

    if ext in [".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"]:
        return {"type": "file", "content": "暂不支持预览"}

    if ext == ".xlsx":
        preview = build_xlsx_preview(file_path)
        if preview:
            return preview

    if ext == ".docx":
        preview = build_doc_spire_pdf_preview(file_path)
        if preview:
            return preview
        preview = build_docx_pdf_preview(file_path)
        if preview:
            return preview
        preview = build_docx_mammoth_preview(file_path)
        if preview:
            return preview
        preview = build_docx_preview(file_path)
        if preview:
            return preview

    if ext in [".ppt", ".pptx"]:
        preview = build_ppt_pdf_preview(file_path)
        if preview:
            return preview
        if ext == ".pptx":
            preview = build_pptx_preview(file_path)
            if preview:
                return preview

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return {"type": "text", "content": f.read(12000)}
    except Exception:
        return {"type": "file", "content": os.path.basename(file_path)}


def build_onlyoffice_preview(file_path: str, request: Request = None) -> dict:
    """生成 OnlyOffice 在线预览配置。"""
    if not ONLYOFFICE_DOCUMENT_SERVER:
        return {}

    ext = os.path.splitext(file_path)[1].lower().lstrip(".")
    document_type = {
        "doc": "word",
        "docx": "word",
        "xls": "cell",
        "xlsx": "cell",
        "ppt": "slide",
        "pptx": "slide",
    }.get(ext)
    if not document_type:
        return {}

    base_url = APP_PUBLIC_BASE_URL
    if not base_url and request is not None:
        base_url = str(request.base_url).rstrip("/")
    if not base_url:
        return {}

    file_id = uuid.uuid4().hex
    PREVIEW_FILES[file_id] = os.path.abspath(file_path)
    file_url = f"{base_url}/preview-file/{file_id}"
    title = os.path.basename(file_path)
    config = {
        "type": "desktop",
        "width": "100%",
        "height": "100%",
        "documentType": document_type,
        "document": {
            "fileType": ext,
            "key": f"{file_id}-{int(os.path.getmtime(file_path))}",
            "title": title,
            "url": file_url,
            "permissions": {
                "download": True,
                "edit": False,
                "print": True,
            },
        },
        "editorConfig": {
            "lang": "zh-CN",
            "mode": "view",
            "customization": {
                "compactToolbar": True,
                "forcesave": False,
            },
        },
    }
    if ONLYOFFICE_JWT_SECRET:
        config["token"] = make_onlyoffice_token(config)

    return {
        "type": "onlyoffice",
        "document_server": ONLYOFFICE_DOCUMENT_SERVER,
        "config": config,
    }


def make_onlyoffice_token(payload: dict) -> str:
    """为 OnlyOffice 配置生成 JWT token。"""
    header = {"alg": "HS256", "typ": "JWT"}
    body = dict(payload)
    body["iat"] = int(time.time())
    signing_input = ".".join([
        jwt_base64(json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode("utf-8")),
        jwt_base64(json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")),
    ])
    signature = hmac.new(
        ONLYOFFICE_JWT_SECRET.encode("utf-8"),
        signing_input.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return f"{signing_input}.{jwt_base64(signature)}"


def jwt_base64(value: bytes) -> str:
    """按 JWT 规则进行 URL-safe base64 编码。"""
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def build_pdf_preview(file_path: str) -> dict:
    """把 PDF 每页渲染为 base64 PNG 供前端预览。"""
    doc = fitz.open(file_path)
    images = []
    for page in doc:
        pix = page.get_pixmap(matrix=fitz.Matrix(1.2, 1.2))
        images.append(base64.b64encode(pix.tobytes("png")).decode())
    page_count = len(doc)
    doc.close()
    return {"type": "pdf", "images": images, "page_count": page_count}


def build_docx_pdf_preview(file_path: str) -> dict:
    """尝试使用 docx2pdf 将 DOCX 转 PDF 后预览。"""
    try:
        from docx2pdf import convert
    except Exception:
        return {}

    base_name = os.path.basename(file_path).rsplit(".", 1)[0]
    out_dir = os.path.join("output", "docx_preview")
    os.makedirs(out_dir, exist_ok=True)
    pdf_path = os.path.join(out_dir, f"{base_name}_{uuid.uuid4().hex[:8]}.pdf")

    try:
        convert(file_path, pdf_path)
        if os.path.exists(pdf_path):
            preview = build_pdf_preview(pdf_path)
            preview["converted_from"] = "docx"
            return preview
    except Exception as exc:
        print(f"DOCX to PDF preview failed: {file_path} - {exc}")
    return {}


def build_doc_spire_pdf_preview(file_path: str) -> dict:
    """尝试使用 Spire.Doc 将 DOC/DOCX 转 PDF 后预览。"""
    try:
        from spire.doc import Document, FileFormat
    except Exception:
        return {}

    base_name = os.path.basename(file_path).rsplit(".", 1)[0]
    out_dir = os.path.join("output", "doc_spire_preview")
    os.makedirs(out_dir, exist_ok=True)
    pdf_path = os.path.join(out_dir, f"{base_name}_{uuid.uuid4().hex[:8]}.pdf")
    doc = None

    try:
        doc = Document()
        doc.LoadFromFile(file_path)
        doc.SaveToFile(pdf_path, FileFormat.PDF)
        if os.path.exists(pdf_path):
            preview = build_pdf_preview(pdf_path)
            preview["converted_from"] = "docx"
            return preview
    except Exception as exc:
        print(f"Spire DOCX to PDF preview failed: {file_path} - {exc}")
    finally:
        try:
            if doc:
                doc.Close()
        except Exception:
            pass
    return {}


def build_docx_mammoth_preview(file_path: str) -> dict:
    """尝试使用 mammoth 将 DOCX 转为 HTML 预览。"""
    try:
        import mammoth
    except Exception:
        return {}

    try:
        with open(file_path, "rb") as docx_file:
            result = mammoth.convert_to_html(docx_file)
        html = sanitize_preview_html(result.value)
        return {
            "type": "word_html",
            "content": os.path.basename(file_path),
            "html": html,
            "messages": [str(message) for message in result.messages],
        }
    except Exception as exc:
        print(f"Mammoth DOCX preview failed: {file_path} - {exc}")
        return {}


def sanitize_preview_html(html: str) -> str:
    """清理预览 HTML 中的脚本和事件属性。"""
    html = re.sub(r"<\s*(script|style)\b[\s\S]*?<\s*/\s*\1\s*>", "", html or "", flags=re.I)
    html = re.sub(r"\son\w+\s*=\s*(['\"]).*?\1", "", html, flags=re.I)
    html = re.sub(r"\s(href|src)\s*=\s*(['\"])\s*javascript:[\s\S]*?\2", "", html, flags=re.I)
    return html


def build_ppt_pdf_preview(file_path: str) -> dict:
    """尝试使用 PowerPoint COM 将 PPT/PPTX 转 PDF 后预览。"""
    try:
        import win32com.client
    except Exception:
        return {}

    base_name = os.path.basename(file_path).rsplit(".", 1)[0]
    out_dir = os.path.abspath(os.path.join("output", "ppt_preview"))
    os.makedirs(out_dir, exist_ok=True)
    pdf_path = os.path.join(out_dir, f"{base_name}_{uuid.uuid4().hex[:8]}.pdf")
    abs_file_path = os.path.abspath(file_path)
    powerpoint = None
    presentation = None

    try:
        powerpoint = win32com.client.DispatchEx("PowerPoint.Application")
        powerpoint.DisplayAlerts = 0
        presentation = powerpoint.Presentations.Open(abs_file_path, WithWindow=False)
        try:
            presentation.ExportAsFixedFormat(pdf_path, 2, 2)
        except Exception:
            presentation.SaveAs(pdf_path, 32)
        if os.path.exists(pdf_path):
            preview = build_pdf_preview(pdf_path)
            preview["converted_from"] = "ppt"
            return preview
    except Exception as exc:
        print(f"PPT to PDF preview failed: {file_path} - {exc}")
    finally:
        try:
            if presentation:
                presentation.Close()
        except Exception:
            pass
        try:
            if powerpoint:
                powerpoint.Quit()
        except Exception:
            pass
    return {}


def build_xlsx_preview(file_path: str) -> dict:
    """读取 XLSX 首个工作表并生成表格预览数据。"""
    try:
        with zipfile.ZipFile(file_path) as zf:
            shared_strings = read_xlsx_shared_strings(zf)
            sheet_name = first_xlsx_sheet_path(zf)
            if not sheet_name:
                return {"type": "file", "content": os.path.basename(file_path)}

            root = ET.fromstring(zf.read(sheet_name))
            ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            rows = []
            for row in root.findall(".//x:sheetData/x:row", ns):
                values = []
                for cell in row.findall("x:c", ns):
                    col_index = xlsx_column_index(cell.attrib.get("r", ""))
                    while col_index and len(values) < col_index - 1:
                        values.append("")
                    values.append(read_xlsx_cell(cell, shared_strings, ns))
                rows.append(values)

            return {
                "type": "spreadsheet",
                "content": os.path.basename(file_path),
                "rows": rows,
                "row_count": len(rows),
                "truncated": False,
            }
    except Exception as exc:
        print(f"XLSX preview failed: {file_path} - {exc}")
        return {"type": "file", "content": os.path.basename(file_path)}


def read_xlsx_shared_strings(zf: zipfile.ZipFile) -> list:
    """读取 XLSX sharedStrings.xml 中的共享字符串。"""
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    strings = []
    for item in root.findall("x:si", ns):
        parts = [node.text or "" for node in item.findall(".//x:t", ns)]
        strings.append("".join(parts))
    return strings


def first_xlsx_sheet_path(zf: zipfile.ZipFile) -> str:
    """获取 XLSX 中第一个工作表 XML 路径。"""
    names = set(zf.namelist())
    if "xl/worksheets/sheet1.xml" in names:
        return "xl/worksheets/sheet1.xml"
    sheets = sorted(name for name in names if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"))
    return sheets[0] if sheets else ""


def read_xlsx_cell(cell, shared_strings: list, ns: dict) -> str:
    """读取 XLSX 单元格文本。"""
    cell_type = cell.attrib.get("t")
    value_node = cell.find("x:v", ns)
    inline_node = cell.find("x:is", ns)

    if inline_node is not None:
        return "".join(node.text or "" for node in inline_node.findall(".//x:t", ns))
    if value_node is None or value_node.text is None:
        return ""

    raw = value_node.text
    if cell_type == "s":
        try:
            return shared_strings[int(raw)]
        except Exception:
            return raw
    return raw


def xlsx_column_index(cell_ref: str) -> int:
    """把 Excel 列名转换为从 1 开始的列序号。"""
    letters = "".join(ch for ch in str(cell_ref or "") if ch.isalpha()).upper()
    if not letters:
        return 0
    index = 0
    for ch in letters:
        index = index * 26 + ord(ch) - ord("A") + 1
    return index


def build_docx_preview(file_path: str) -> dict:
    """直接解析 DOCX XML，生成简化的段落和表格预览。"""
    try:
        with zipfile.ZipFile(file_path) as zf:
            if "word/document.xml" not in zf.namelist():
                return {"type": "file", "content": os.path.basename(file_path)}

            root = ET.fromstring(zf.read("word/document.xml"))
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            body = root.find("w:body", ns)
            blocks = []
            if body is None:
                return {"type": "word", "content": os.path.basename(file_path), "blocks": blocks}

            for child in list(body):
                tag = child.tag.rsplit("}", 1)[-1]
                if tag == "p":
                    text = docx_paragraph_text(child, ns)
                    if text:
                        blocks.append({"type": "paragraph", "text": text})
                elif tag == "tbl":
                    rows = []
                    for tr in child.findall("w:tr", ns):
                        cells = []
                        for tc in tr.findall("w:tc", ns):
                            parts = [docx_paragraph_text(p, ns) for p in tc.findall("w:p", ns)]
                            cells.append("\n".join(part for part in parts if part))
                        rows.append(cells)
                    if rows:
                        blocks.append({"type": "table", "rows": rows})

            return {
                "type": "word",
                "content": os.path.basename(file_path),
                "blocks": blocks,
                "page_count": max(1, (len(blocks) + 27) // 28),
            }
    except Exception as exc:
        print(f"DOCX preview failed: {file_path} - {exc}")
        return {"type": "file", "content": os.path.basename(file_path)}


def docx_paragraph_text(paragraph, ns: dict) -> str:
    """提取 DOCX 段落中的文本内容。"""
    parts = []
    for child in paragraph.iter():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "t" and child.text:
            parts.append(child.text)
        elif tag == "tab":
            parts.append("\t")
    return "".join(parts).strip()


def build_pptx_preview(file_path: str) -> dict:
    """直接解析 PPTX XML，生成每页文本预览。"""
    try:
        with zipfile.ZipFile(file_path) as zf:
            slide_names = sorted(
                name for name in zf.namelist()
                if name.startswith("ppt/slides/slide") and name.endswith(".xml")
            )
            ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
            slides = []
            for index, slide_name in enumerate(slide_names, start=1):
                root = ET.fromstring(zf.read(slide_name))
                texts = []
                for node in root.findall(".//a:t", ns):
                    if node.text:
                        texts.append(node.text)
                slides.append({
                    "index": index,
                    "texts": texts,
                })
            return {
                "type": "presentation",
                "content": os.path.basename(file_path),
                "slides": slides,
                "page_count": len(slides),
            }
    except Exception as exc:
        print(f"PPTX preview failed: {file_path} - {exc}")
        return {"type": "file", "content": os.path.basename(file_path)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
