import asyncio
import io
import json
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from urllib.parse import urlparse
from html import unescape
from html.parser import HTMLParser
from xml.sax.saxutils import escape
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import requests
import urllib3
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from minio import Minio

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def load_env_file(path: str = ".env") -> None:
    """读取本地 .env 文件，已经存在的系统环境变量不会被覆盖。"""
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

MINERU_URL = os.getenv("MINERU_URL", "http://10.89.1.235:7803/file_parse")
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "")
DOCUMENT_CONVERT_URL = os.getenv("DOCUMENT_CONVERT_URL", "http://10.89.31.94:8009/convert")
LIBREOFFICE_BIN = os.getenv("LIBREOFFICE_BIN", "libreoffice")
MINIO_PRESIGNED_DAYS = int(os.getenv("MINIO_PRESIGNED_DAYS", "7"))
MINIO_PUBLIC_PREFIX = os.getenv("MINIO_PUBLIC_PREFIX", "mineru")
MINIO_PUBLIC_BASE_URL = os.getenv("MINIO_PUBLIC_BASE_URL", "https://chat-s3.ecorubbercloud.com")
PARSE_MAX_CONCURRENT_JOBS = int(os.getenv("PARSE_MAX_CONCURRENT_JOBS", "4"))
MINERU_LANG_LIST = os.getenv("MINERU_LANG_LIST", "ch")

IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
DIRECT_MINERU_EXTS = {".pdf", ".docx", ".pptx", ".xlsx"} | IMAGE_EXTS
CSV_TO_XLSX_EXTS = {".csv"}
# 旧版 Excel 转成 xlsx 后再交给 MinerU，通常比转 PDF 更能保留表格结构。
CONVERT_TO_XLSX_EXTS = {".xls"}
# 暂时只开放当前实际需要的转换格式，避免入口过宽导致不稳定。
CONVERT_TO_PPTX_EXTS = {".ppt"}
CONVERT_TO_PDF_EXTS = {".doc"}

app = FastAPI(title="MinerU Markdown API")
PARSE_JOBS = {}
PARSE_JOBS_LOCK = asyncio.Lock()
PARSE_SEMAPHORE = asyncio.Semaphore(PARSE_MAX_CONCURRENT_JOBS)

MAX_DOCUMENT_PAGES = 100


class RejectedTaskError(RuntimeError):
    pass


@app.get("/health")
async def health():
    """健康检查接口。"""
    return {"status": "ok"}


@app.post("/parse-md")
async def parse_md_api(
    file: UploadFile = File(...),
    user_id: str = Form("anonymous"),
):
    """上传文档并返回图片路径已经替换为 MinIO URL 的 Markdown。"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="missing filename")

    suffix = os.path.splitext(file.filename)[1].lower()
    if suffix not in DIRECT_MINERU_EXTS and suffix not in CSV_TO_XLSX_EXTS and suffix not in CONVERT_TO_XLSX_EXTS and suffix not in CONVERT_TO_PPTX_EXTS and suffix not in CONVERT_TO_PDF_EXTS and suffix not in {".txt", ".md", ".markdown"}:
        raise HTTPException(status_code=400, detail=f"unsupported file type: {suffix or 'unknown'}")

    task_id = new_task_id()
    temp_dir = tempfile.mkdtemp(prefix="mineru_md_")
    file_path = os.path.join(temp_dir, safe_filename(file.filename))
    await asyncio.to_thread(write_bytes_file, file_path, await file.read())

    await set_job(task_id, {
        "task_id": task_id,
        "user_id": user_id,
        "filename": file.filename,
        "status": "queued",
        "progress": 0,
        "message": "任务已提交，等待解析",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "result": None,
        "error": None,
    })

    asyncio.create_task(run_parse_job_async(task_id, file_path, file.filename, user_id, temp_dir))
    return await public_job_status(task_id)


@app.get("/parse-md/{task_id}")
async def get_parse_md_status(task_id: str):
    """查询 Markdown 解析任务状态，完成后返回 Markdown 内容和文件 URL。"""
    if not await get_job(task_id):
        raise HTTPException(status_code=404, detail="task not found")
    return await public_job_status(task_id)


async def run_parse_job_async(task_id: str, file_path: str, filename: str, user_id: str, temp_dir: str) -> None:
    """后台执行解析任务，并在结束后清理临时目录。"""
    async with PARSE_SEMAPHORE:
        try:
            await update_job(task_id, status="running", progress=10, message="started")
            result = await parse_to_replaced_markdown(
                file_path,
                original_filename=filename,
                user_id=user_id,
                task_id=task_id,
            )
            await update_job(
                task_id,
                status="done",
                progress=100,
                message="done",
                result=result,
                error=None,
            )
        except RejectedTaskError as e:
            await update_job(
                task_id,
                status="failed",
                progress=100,
                message="failed",
                error=str(e),
            )
        except Exception as e:
            await update_job(
                task_id,
                status="failed",
                progress=100,
                message="failed",
                error=str(e),
            )
        finally:
            await asyncio.to_thread(shutil.rmtree, temp_dir, True)


def run_parse_job_legacy(task_id: str, file_path: str, filename: str, user_id: str, temp_dir: str) -> None:
    """后台执行解析任务，并在结束后清理临时目录。"""
    PARSE_SEMAPHORE.acquire()
    try:
        update_job(task_id, status="running", progress=10, message="开始解析")
        result = parse_to_replaced_markdown(
            file_path,
            original_filename=filename,
            user_id=user_id,
            task_id=task_id,
        )
        update_job(
            task_id,
            status="done",
            progress=100,
            message="解析完成",
            result=result,
            error=None,
        )
    except Exception as e:
        update_job(
            task_id,
            status="failed",
            progress=100,
            message="解析失败",
            error=str(e),
        )
    finally:
        PARSE_SEMAPHORE.release()
        shutil.rmtree(temp_dir, ignore_errors=True)


def new_task_id() -> str:
    """生成解析任务 ID。"""
    return datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]


async def set_job(task_id: str, job: dict) -> None:
    """写入完整任务状态。"""
    async with PARSE_JOBS_LOCK:
        PARSE_JOBS[task_id] = job


async def get_job(task_id: str) -> dict | None:
    """读取任务状态副本。"""
    async with PARSE_JOBS_LOCK:
        job = PARSE_JOBS.get(task_id)
        return dict(job) if job else None


async def update_job(task_id: str, **updates) -> None:
    """局部更新任务状态。"""
    if not task_id:
        return
    async with PARSE_JOBS_LOCK:
        job = PARSE_JOBS.get(task_id)
        if not job:
            return
        job.update(updates)
        job["updated_at"] = datetime.now().isoformat(timespec="seconds")


async def public_job_status(task_id: str) -> dict:
    """返回给调用方的任务状态；完成后展开结果字段。"""
    job = await get_job(task_id)
    if not job:
        raise HTTPException(status_code=404, detail="task not found")
    response = {
        "task_id": task_id,
        "user_id": job.get("user_id"),
        "filename": job.get("filename"),
        "status": job.get("status"),
        "progress": job.get("progress", 0),
        "message": job.get("message", ""),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "error": job.get("error"),
    }
    if job.get("status") == "done" and isinstance(job.get("result"), dict):
        response.update(job["result"])
    return response


async def parse_to_replaced_markdown(
    file_path: str,
    original_filename: str | None = None,
    user_id: str = "anonymous",
    task_id: str | None = None,
) -> dict:
    """核心函数：解析文档，上传图片到 MinIO，并返回已替换图片路径的 Markdown。"""
    original_filename = original_filename or os.path.basename(file_path)
    ext = os.path.splitext(original_filename)[1].lower()
    task_id = task_id or new_task_id()
    validate_input_limits(file_path, ext)
    original_url = await save_file_to_minio(
        task_id,
        user_id,
        file_path,
        original_object_name(task_id, user_id, original_filename),
    )

    if ext in {".txt", ".md", ".markdown"}:
        markdown = await asyncio.to_thread(read_text_file, file_path)
        markdown = await asyncio.to_thread(convert_html_tables_to_markdown, markdown)
        await update_job(task_id, progress=80, message="saving markdown")
        markdown_url = await save_markdown_to_minio(task_id, user_id, markdown)
        json_url = await save_json_to_minio(task_id, user_id, {"type": "text", "content": markdown})
        return {
            "task_id": task_id,
            "filename": original_filename,
            "format": "markdown",
            "markdown_url": markdown_url,
            "markdown_object": markdown_object_name(task_id, user_id),
            "json_url": json_url,
            "json_object": json_object_name(task_id, user_id),
            "original_url": original_url,
            "original_object": original_object_name(task_id, user_id, original_filename),
            "parse_file_url": original_url,
            "parse_file_object": original_object_name(task_id, user_id, original_filename),
            "image_urls": {},
        }

    await update_job(task_id, progress=20, message="preparing file")
    parse_path = await prepare_file_for_mineru_async(file_path, ext)
    parse_file_object = original_object_name(task_id, user_id, original_filename)
    parse_file_url = original_url
    if os.path.abspath(parse_path) != os.path.abspath(file_path):
        parse_file_object = converted_object_name(task_id, user_id, parse_path)
        parse_file_url = await save_file_to_minio(task_id, user_id, parse_path, parse_file_object)

    await update_job(task_id, progress=35, message="calling MinerU")
    markdown, images, layout = await call_mineru_for_markdown_async(parse_path)

    await update_job(task_id, progress=70, message="uploading images")
    referenced = await asyncio.to_thread(collect_referenced_images, markdown, layout)
    upload_images = {name: data for name, data in images.items() if name in referenced}
    image_urls = await upload_images_to_minio_async(task_id, user_id, upload_images)
    await update_job(task_id, progress=85, message="replacing image paths")
    markdown, layout = await asyncio.to_thread(post_process_mineru_output, markdown, layout, image_urls)
    await update_job(task_id, progress=90, message="saving markdown")
    markdown_url = await save_markdown_to_minio(task_id, user_id, markdown)
    json_url = await save_json_to_minio(task_id, user_id, layout)

    return {
        "task_id": task_id,
        "filename": original_filename,
        "format": "markdown",
        "markdown_url": markdown_url,
        "markdown_object": markdown_object_name(task_id, user_id),
        "json_url": json_url,
        "json_object": json_object_name(task_id, user_id),
        "original_url": original_url,
        "original_object": original_object_name(task_id, user_id, original_filename),
        "parse_file_url": parse_file_url,
        "parse_file_object": parse_file_object,
        "image_urls": image_urls,
        "image_count": len(upload_images),
        "skipped_image_count": len(images) - len(upload_images),
    }


def prepare_file_for_mineru(file_path: str, ext: str) -> str:
    """把 MinerU 不直接支持的格式先转换成 PDF。"""
    if ext in DIRECT_MINERU_EXTS:
        return file_path
    if ext in CSV_TO_XLSX_EXTS:
        return convert_csv_to_xlsx(file_path)
    if ext in CONVERT_TO_XLSX_EXTS:
        return convert_file_to_xlsx(file_path)
    if ext in CONVERT_TO_PPTX_EXTS:
        return convert_file_to_pptx(file_path)
    if ext in CONVERT_TO_PDF_EXTS:
        return convert_file_to_pdf(file_path)
    raise RuntimeError(f"unsupported file type: {ext}")


def validate_input_limits(file_path: str, ext: str) -> None:
    if ext == ".pdf":
        validate_pdf_page_limit(file_path)


def validate_pdf_page_limit(file_path: str) -> None:
    pages = count_pdf_pages(file_path)
    if pages is not None and pages > MAX_DOCUMENT_PAGES:
        raise RejectedTaskError(f"page count exceeds limit: {pages} > {MAX_DOCUMENT_PAGES}")


def count_pdf_pages(file_path: str) -> int | None:
    try:
        import fitz
        with fitz.open(file_path) as doc:
            return len(doc)
    except Exception:
        try:
            data = read_bytes_file(file_path)
            return len(re.findall(rb"/Type\s*/Page\b", data))
        except Exception:
            return None


async def prepare_file_for_mineru_async(file_path: str, ext: str) -> str:
    """异步准备 MinerU 输入文件。"""
    if ext in DIRECT_MINERU_EXTS:
        return file_path
    if ext in CSV_TO_XLSX_EXTS:
        return await asyncio.to_thread(convert_csv_to_xlsx, file_path)
    if ext in CONVERT_TO_XLSX_EXTS:
        return await asyncio.to_thread(convert_file_to_xlsx, file_path)
    if ext in CONVERT_TO_PPTX_EXTS:
        return await asyncio.to_thread(convert_file_to_pptx, file_path)
    if ext in CONVERT_TO_PDF_EXTS:
        return await asyncio.to_thread(convert_file_to_pdf, file_path)
    raise RuntimeError(f"unsupported file type: {ext}")


def convert_file_to_pdf(file_path: str) -> str:
    """先调用公司转换接口转 PDF，失败后用 LibreOffice 兜底。"""
    errors = []
    if DOCUMENT_CONVERT_URL:
        try:
            return convert_file_by_api(file_path, "pdf")
        except Exception as e:
            errors.append(f"api convert failed: {e}")
    try:
        return convert_file_by_libreoffice(file_path, "pdf")
    except Exception as e:
        errors.append(f"libreoffice convert failed: {e}")
    raise RuntimeError("; ".join(errors) or "convert failed")


def convert_file_to_xlsx(file_path: str) -> str:
    """把旧版表格文件转换成 xlsx，再交给 MinerU 解析。"""
    errors = []
    if DOCUMENT_CONVERT_URL:
        try:
            return convert_file_by_api(file_path, "xlsx")
        except Exception as e:
            errors.append(f"api convert failed: {e}")
    try:
        return convert_file_by_libreoffice(file_path, "xlsx")
    except Exception as e:
        errors.append(f"libreoffice convert failed: {e}")
    raise RuntimeError("; ".join(errors) or "convert failed")


def convert_file_to_pptx(file_path: str) -> str:
    """把旧版 PPT 转换成 pptx，再交给 MinerU 原生解析。"""
    errors = []
    if DOCUMENT_CONVERT_URL:
        try:
            return convert_file_by_api(file_path, "pptx")
        except Exception as e:
            errors.append(f"api convert failed: {e}")
    try:
        return convert_file_by_libreoffice(file_path, "pptx")
    except Exception as e:
        errors.append(f"libreoffice convert failed: {e}")
    raise RuntimeError("; ".join(errors) or "convert failed")


def convert_csv_to_xlsx(file_path: str) -> str:
    """Convert CSV text to a simple XLSX workbook for MinerU parsing."""
    import csv

    text = read_text_file(file_path)
    rows = list(csv.reader(text.splitlines()))
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    xlsx_path = os.path.join(os.path.dirname(file_path), f"{base_name}_{uuid.uuid4().hex[:8]}.xlsx")

    sheet_rows = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for col_index, value in enumerate(row, start=1):
            ref = f"{column_name(col_index)}{row_index}"
            cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(value)}</t></is></c>')
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')

    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(sheet_rows)}</sheetData>'
        '</worksheet>'
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets>'
        '</workbook>'
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '</Relationships>'
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '</Types>'
    )

    with zipfile.ZipFile(xlsx_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return xlsx_path


def column_name(index: int) -> str:
    """Return an Excel column name such as A, Z, AA."""
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name or "A"


def request_post(url: str, **kwargs) -> requests.Response:
    """调用内部服务时不继承本机代理配置，避免请求被错误代理拦截。"""
    session = requests.Session()
    session.trust_env = False
    try:
        return session.post(url, **kwargs)
    finally:
        session.close()


def request_get(url: str, **kwargs) -> requests.Response:
    """调用内部服务时不继承本机代理配置，避免请求被错误代理拦截。"""
    session = requests.Session()
    session.trust_env = False
    try:
        return session.get(url, **kwargs)
    finally:
        session.close()


def extract_converted_file_from_response(response: requests.Response, output_format: str) -> bytes:
    """兼容转换服务直接返回文件，或返回 JSON 下载地址两种情况。"""
    output_format = output_format.lower().strip().lstrip(".")
    if output_format == "pdf" and response.content.startswith(b"%PDF"):
        return response.content
    if output_format in {"xlsx", "pptx"} and response.content.startswith(b"PK"):
        return response.content

    content_type = response.headers.get("content-type", "").lower()
    if "json" not in content_type:
        raise RuntimeError(f"convert api returned non-{output_format} content: {content_type or 'unknown'}")

    payload = response.json()
    file_url = find_converted_file_url(payload, output_format)
    if not file_url:
        raise RuntimeError(f"convert api JSON missing {output_format} url")

    file_resp = request_get(file_url, timeout=300)
    if file_resp.status_code != 200:
        raise RuntimeError(f"download converted {output_format} failed: {file_resp.status_code} {file_resp.text[:300]}")
    return file_resp.content


def extract_pdf_from_convert_response(response: requests.Response) -> bytes:
    return extract_converted_file_from_response(response, "pdf")


def find_converted_file_url(value, output_format: str) -> str:
    """从嵌套 JSON 中查找转换后文件的 URL 或 MinIO object path。"""
    if isinstance(value, dict):
        for key in ("file_url", "fileUrl", "download_url", "downloadUrl", "url", f"{output_format}_url", f"{output_format}Url"):
            item = normalize_converted_file_reference(value.get(key), output_format)
            if item:
                return item
        for item in value.values():
            found = find_converted_file_url(item, output_format)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = find_converted_file_url(item, output_format)
            if found:
                return found
    else:
        return normalize_converted_file_reference(value, output_format)
    return ""


def normalize_converted_file_reference(value, output_format: str) -> str:
    """把完整 URL 或 MinIO object path 统一成可下载的文件 URL。"""
    if not isinstance(value, str):
        return ""
    value = value.strip()
    suffix = f".{output_format.lower().strip().lstrip('.')}"
    parsed = urlparse(value)
    path = parsed.path.lower().split("?", 1)[0]
    if parsed.scheme in {"http", "https"} and parsed.netloc and path.endswith(suffix):
        return value
    if not parsed.scheme and value.lower().split("?", 1)[0].endswith(suffix):
        bucket_prefix = f"{MINIO_BUCKET.strip('/')}/"
        object_name = value[len(bucket_prefix):] if bucket_prefix and value.startswith(bucket_prefix) else value
        return public_minio_url(object_name)
    return ""


def convert_file_by_api(file_path: str, output_format: str) -> str:
    """调用远程 LibreOffice 转换服务，并把转换结果保存到本地临时文件。"""
    output_format = output_format.lower().strip().lstrip(".")
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    output_path = os.path.join(os.path.dirname(file_path), f"{base_name}_{uuid.uuid4().hex[:8]}.{output_format}")
    with open(file_path, "rb") as f:
        files = {"file": (converter_upload_filename(file_path), f)}
        data = {"output_format": output_format}
        response = request_post(DOCUMENT_CONVERT_URL, files=files, data=data, timeout=300)
    if response.status_code != 200:
        raise RuntimeError(f"{response.status_code} {response.text[:300]}")
    converted_data = extract_converted_file_from_response(response, output_format)
    validate_converted_data(converted_data, output_format)
    with open(output_path, "wb") as f:
        f.write(converted_data)
    return output_path


def converter_upload_filename(file_path: str) -> str:
    """上传给转换服务时使用英文临时文件名，避免中文响应头编码失败。"""
    ext = os.path.splitext(file_path)[1].lower() or ".bin"
    return f"input_{uuid.uuid4().hex[:8]}{ext}"


def validate_converted_data(data: bytes, output_format: str) -> None:
    """把转换结果交给 MinerU 前，先用文件头做轻量校验。"""
    output_format = output_format.lower().strip().lstrip(".")
    if output_format == "pdf" and not data.startswith(b"%PDF"):
        raise RuntimeError("convert api did not return a PDF")
    if output_format in {"xlsx", "pptx"} and not data.startswith(b"PK"):
        raise RuntimeError(f"convert api did not return a {output_format.upper()}")


def convert_file_to_pdf_by_api(file_path: str) -> str:
    return convert_file_by_api(file_path, "pdf")


def convert_file_by_libreoffice(file_path: str, output_format: str) -> str:
    """远程转换服务失败时，尝试使用本机 LibreOffice 兜底转换。"""
    output_format = output_format.lower().strip().lstrip(".")
    output_dir = os.path.dirname(file_path)
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    output_path = os.path.join(output_dir, f"{base_name}.{output_format}")
    result = subprocess.run(
        [
            LIBREOFFICE_BIN,
            "--headless",
            "--convert-to",
            output_format,
            "--outdir",
            output_dir,
            file_path,
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or f"return code {result.returncode}")
    if not os.path.exists(output_path):
        raise RuntimeError(f"LibreOffice did not generate {output_format.upper()}")
    return output_path


def convert_file_to_pdf_by_api_legacy(file_path: str) -> str:
    """调用公司内部转换服务，把文件转换为 PDF。"""
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    pdf_path = os.path.join(os.path.dirname(file_path), f"{base_name}_{uuid.uuid4().hex[:8]}.pdf")
    with open(file_path, "rb") as f:
        files = {"file": (os.path.basename(file_path), f)}
        response = request_post(DOCUMENT_CONVERT_URL, files=files, timeout=300)
    if response.status_code != 200:
        raise RuntimeError(f"{response.status_code} {response.text[:300]}")
    pdf_data = extract_pdf_from_convert_response(response)
    if not pdf_data.startswith(b"%PDF"):
        raise RuntimeError("convert api did not return a PDF")
    with open(pdf_path, "wb") as f:
        f.write(pdf_data)
    return pdf_path


def convert_file_to_pdf_by_libreoffice(file_path: str) -> str:
    """使用本机 LibreOffice headless 模式转换 PDF。"""
    output_dir = os.path.dirname(file_path)
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    pdf_path = os.path.join(output_dir, f"{base_name}.pdf")
    result = subprocess.run(
        [
            LIBREOFFICE_BIN,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            output_dir,
            file_path,
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or f"return code {result.returncode}")
    if not os.path.exists(pdf_path):
        raise RuntimeError("LibreOffice did not generate PDF")
    return pdf_path


def call_mineru_for_markdown(file_path: str) -> tuple[str, dict, dict]:
    """调用 MinerU，同步解析 ZIP 响应里的 Markdown 和图片。"""
    ext = os.path.splitext(file_path)[1].lower()
    with open(file_path, "rb") as f:
        files = [("files", (os.path.basename(file_path), f))]
        data = mineru_request_data(ext)
        resp = request_post(MINERU_URL, files=files, data=data, timeout=1800)

    if resp.status_code != 200:
        detail = resp.text[:500] if resp.text else ""
        raise RuntimeError(f"MinerU parse failed: {resp.status_code} {detail}")

    markdown = ""
    images = {}
    layout = {}
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        for name in zf.namelist():
            lower = name.lower()
            if lower.endswith((".md", ".markdown")) and not markdown:
                markdown = zf.read(name).decode("utf-8", errors="replace")
            elif lower.endswith(("middle.json", "layout.json")) and not layout:
                layout = json.loads(zf.read(name).decode("utf-8"))
            elif "images/" in name and not name.endswith("/"):
                images[os.path.basename(name)] = zf.read(name)

    if not markdown:
        markdown = layout_to_markdown(layout)
    return markdown, images, layout


def mineru_request_data(ext: str = "") -> list[tuple[str, str | bool]]:
    is_image = ext.lower() in IMAGE_EXTS
    backend = "hybrid-auto-engine" if is_image else "vlm-auto-engine"
    data = [
        ("backend", backend),
        ("response_format_zip", True),
        ("return_middle_json", True),
        ("return_model_output", False),
        ("return_content_list", True),
        ("return_images", True),
    ]
    if is_image:
        data.extend([
            ("parse_method", "auto"),
            ("image_analysis", True),
        ])
    for lang in parse_mineru_lang_list(MINERU_LANG_LIST):
        data.append(("lang_list", lang))
    return data


def parse_mineru_lang_list(value: str) -> list[str]:
    langs = [item.strip() for item in value.split(",") if item.strip()]
    return langs or ["ch"]


async def call_mineru_for_markdown_async(file_path: str) -> tuple[str, dict, dict]:
    """在线程池中调用同步 MinerU 请求，避免阻塞事件循环。"""
    return await asyncio.to_thread(call_mineru_for_markdown, file_path)


def upload_images_to_minio(task_id: str, user_id: str, images: dict) -> dict:
    """并发上传图片到 MinIO，返回本地图片路径到预签名 URL 的映射。"""
    if not images:
        return {}
    client = create_minio_client()
    if client is None:
        raise RuntimeError("MinIO config is incomplete")

    prefix = minio_task_prefix(task_id, user_id)
    image_urls = {}

    def upload_one(item):
        img_name, img_data = item
        object_name = f"{prefix}/images/{img_name}"
        content_type = mimetypes.guess_type(img_name)[0] or "application/octet-stream"
        url = upload_bytes_to_minio(client, object_name, img_data, content_type)
        return img_name, url

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(upload_one, item) for item in images.items()]
        for future in as_completed(futures):
            img_name, url = future.result()
            image_urls[img_name] = url
            image_urls[f"images/{img_name}"] = url
    return image_urls


async def upload_images_to_minio_async(task_id: str, user_id: str, images: dict) -> dict:
    """在线程池中执行同步图片并发上传。"""
    return await asyncio.to_thread(upload_images_to_minio, task_id, user_id, images)


async def save_markdown_to_minio(task_id: str, user_id: str, markdown: str) -> str:
    """Save final Markdown to MinIO and return the public object URL."""
    client = create_minio_client()
    if client is None:
        return ""
    object_name = markdown_object_name(task_id, user_id)
    data = await asyncio.to_thread(markdown_to_bytes, markdown)
    return await asyncio.to_thread(
        upload_bytes_to_minio,
        client,
        object_name,
        data,
        "text/markdown; charset=utf-8",
    )


async def save_json_to_minio(task_id: str, user_id: str, value: dict) -> str:
    """Save MinerU layout JSON to MinIO and return the public object URL."""
    client = create_minio_client()
    if client is None:
        return ""
    object_name = json_object_name(task_id, user_id)
    data = await asyncio.to_thread(json_to_bytes, value)
    return await asyncio.to_thread(
        upload_bytes_to_minio,
        client,
        object_name,
        data,
        "application/json; charset=utf-8",
    )


async def save_file_to_minio(task_id: str, user_id: str, file_path: str, object_name: str) -> str:
    """Save an input or converted file to MinIO and return the public object URL."""
    client = create_minio_client()
    if client is None:
        return ""
    content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    data = await asyncio.to_thread(read_bytes_file, file_path)
    return await asyncio.to_thread(upload_bytes_to_minio, client, object_name, data, content_type)


def upload_bytes_to_minio(client: Minio, object_name: str, data: bytes, content_type: str) -> str:
    """上传字节内容到 MinIO，并返回有效期内可访问的预签名 URL。"""
    client.put_object(
        MINIO_BUCKET,
        object_name,
        io.BytesIO(data),
        len(data),
        content_type=content_type,
    )
    return public_minio_url(object_name)


def markdown_to_bytes(markdown: str) -> bytes:
    return (markdown or "").encode("utf-8")


def json_to_bytes(value: dict) -> bytes:
    return json.dumps(value or {}, ensure_ascii=False, indent=2).encode("utf-8")


def create_minio_client() -> Minio | None:
    """创建 MinIO 客户端，配置不完整时返回 None。"""
    if not all([MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY, MINIO_BUCKET]):
        return None
    return Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=False,
        cert_check=False,
    )


def minio_task_prefix(task_id: str, user_id: str) -> str:
    """生成当前接口上传图片使用的 MinIO 前缀。"""
    safe_user = safe_filename(user_id or "anonymous")
    safe_task = safe_filename(task_id)
    return f"{MINIO_PUBLIC_PREFIX}/users/{safe_user}/tasks/{safe_task}"


def markdown_object_name(task_id: str, user_id: str) -> str:
    """Build the MinIO object name for the final Markdown file."""
    return f"{minio_task_prefix(task_id, user_id)}/result/result.md"


def json_object_name(task_id: str, user_id: str) -> str:
    """Build the MinIO object name for the MinerU layout JSON file."""
    return f"{minio_task_prefix(task_id, user_id)}/result/result.json"


def original_object_name(task_id: str, user_id: str, filename: str) -> str:
    """Build the MinIO object name for the original uploaded file."""
    return f"{minio_task_prefix(task_id, user_id)}/original/{safe_filename(filename)}"


def converted_object_name(task_id: str, user_id: str, file_path: str) -> str:
    """Build the MinIO object name for the converted file used by MinerU."""
    return f"{minio_task_prefix(task_id, user_id)}/converted/{safe_filename(os.path.basename(file_path))}"


def public_minio_url(object_name: str) -> str:
    """Build a stable public MinIO URL, for example https://host/bucket/object."""
    base = MINIO_PUBLIC_BASE_URL.rstrip("/")
    bucket = MINIO_BUCKET.strip("/")
    object_path = object_name.lstrip("/")
    if bucket:
        return f"{base}/{bucket}/{object_path}"
    return f"{base}/{object_path}"


def referenced_markdown_images(markdown: str) -> set:
    """找出 Markdown/HTML 中实际引用到的图片文件名。"""
    refs = set()
    patterns = [
        r"!\[[^\]]*\]\(([^)]+)\)",
        r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"']",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, markdown or "", flags=re.I):
            path = str(match).split("?", 1)[0].strip().strip("\"'")
            name = os.path.basename(path)
            if name:
                refs.add(name)
    return refs


def referenced_layout_images(value) -> set:
    """Find image file names referenced anywhere in MinerU layout JSON."""
    refs = set()
    image_exts = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif")
    if isinstance(value, dict):
        for item in value.values():
            refs.update(referenced_layout_images(item))
    elif isinstance(value, list):
        for item in value:
            refs.update(referenced_layout_images(item))
    elif isinstance(value, str):
        name = os.path.basename(value.split("?", 1)[0].strip().strip("\"'"))
        if name.lower().endswith(image_exts):
            refs.add(name)
    return refs


def collect_referenced_images(markdown: str, layout: dict) -> set:
    refs = referenced_markdown_images(markdown)
    refs.update(referenced_layout_images(layout))
    return refs


def post_process_mineru_output(markdown: str, layout: dict, image_urls: dict) -> tuple[str, dict]:
    markdown = replace_image_refs(markdown, image_urls)
    markdown = convert_html_tables_to_markdown(markdown)
    return markdown, layout


def replace_image_refs(value: str, image_urls: dict) -> str:
    """把 Markdown/HTML 中的本地图片路径替换成 MinIO URL。"""
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
    """Recursively replace image paths in JSON-like data with MinIO URLs."""
    if not image_urls:
        return value
    if isinstance(value, dict):
        return {key: replace_image_refs_in_json(item, image_urls) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_image_refs_in_json(item, image_urls) for item in value]
    if isinstance(value, str):
        return replace_image_refs(value, image_urls)
    return value


class HtmlTableParser(HTMLParser):
    """Extract rows from one HTML table fragment."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.rows = []
        self.row_cell_types = []
        self._current_row = None
        self._current_types = None
        self._current_cell = None
        self._current_cell_type = None
        self._cell_depth = 0
        self._in_table = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "table":
            self._in_table += 1
            return
        if not self._in_table:
            return
        if tag == "tr":
            self._current_row = []
            self._current_types = []
        elif tag in {"td", "th"} and self._current_row is not None:
            self._current_cell = []
            self._current_cell_type = tag
            self._cell_depth = 1
        elif self._current_cell is not None:
            self._cell_depth += 1
            if tag == "br":
                self._current_cell.append("<br>")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"td", "th"} and self._current_cell is not None:
            text = clean_table_cell("".join(self._current_cell))
            self._current_row.append(text)
            self._current_types.append(self._current_cell_type or "td")
            self._current_cell = None
            self._current_cell_type = None
            self._cell_depth = 0
        elif tag == "tr" and self._current_row is not None:
            if any(cell.strip() for cell in self._current_row):
                self.rows.append(self._current_row)
                self.row_cell_types.append(self._current_types or [])
            self._current_row = None
            self._current_types = None
        elif tag == "table" and self._in_table:
            self._in_table -= 1
        elif self._current_cell is not None and self._cell_depth:
            self._cell_depth -= 1

    def handle_data(self, data):
        if self._current_cell is not None:
            self._current_cell.append(data)

    def handle_entityref(self, name):
        if self._current_cell is not None:
            self._current_cell.append(f"&{name};")

    def handle_charref(self, name):
        if self._current_cell is not None:
            self._current_cell.append(f"&#{name};")


def convert_html_tables_to_markdown(markdown: str) -> str:
    """Convert HTML <table> blocks in Markdown text to native Markdown tables."""
    if not markdown or "<table" not in markdown.lower():
        return markdown or ""

    def convert_match(match):
        html_table = match.group(0)
        parser = HtmlTableParser()
        try:
            parser.feed(html_table)
            parser.close()
            return html_table_to_markdown(parser.rows, parser.row_cell_types) or html_table
        except Exception:
            return html_table

    return re.sub(r"(?is)<table\b.*?</table>", convert_match, markdown)


def html_table_to_markdown(rows: list[list[str]], row_cell_types: list[list[str]]) -> str:
    """Render extracted table rows as a GitHub-style Markdown table."""
    rows = [[clean_table_cell(cell) for cell in row] for row in rows if row]
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    if width <= 0:
        return ""

    normalized = [row + [""] * (width - len(row)) for row in rows]
    header = normalized[0]
    body = normalized[1:]

    lines = [
        "| " + " | ".join(escape_markdown_table_cell(cell) for cell in header) + " |",
        "| " + " | ".join("---" for _ in range(width)) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(escape_markdown_table_cell(cell) for cell in row) + " |")
    return "\n\n" + "\n".join(lines) + "\n\n"


def clean_table_cell(value: str) -> str:
    """Normalize whitespace and HTML entities in a table cell."""
    text = unescape(value or "")
    text = re.sub(r"(?i)<br\s*/?>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def escape_markdown_table_cell(value: str) -> str:
    """Escape characters that break Markdown table cells."""
    return clean_table_cell(value).replace("\\", "\\\\").replace("|", "\\|")


def layout_to_markdown(layout: dict) -> str:
    """当 MinerU 没有返回 md 文件时，从 layout 中提取文本兜底。"""
    lines = []
    for page in layout.get("pdf_info", []):
        page_no = page.get("page_idx", 0) + 1
        page_lines = []
        for key in ["para_blocks", "preproc_blocks"]:
            for block in page.get(key, []):
                text = extract_text(block)
                if text:
                    page_lines.append(text)
        if page_lines:
            lines.append(f"## Page {page_no}")
            lines.extend(page_lines)
    return "\n\n".join(lines).strip()


def extract_text(block: dict) -> str:
    """递归提取 MinerU layout 块里的文本。"""
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


def safe_filename(value: str) -> str:
    """生成适合本地文件和对象路径使用的安全名称。"""
    value = os.path.basename(value or "file")
    return re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fff]+", "_", value) or "file"


def write_bytes_file(path: str, data: bytes) -> None:
    with open(path, "wb") as f:
        f.write(data)


def read_text_file(path: str) -> str:
    data = read_bytes_file(path)
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def read_bytes_file(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8010)
