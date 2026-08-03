import os
import base64
import difflib
import json
import re
import shutil
import tempfile
import time
import asyncio
from urllib.parse import urlparse
import uuid
import csv
import zipfile
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import fitz
import requests
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse


MINERU_MD_API_URL = os.getenv("MINERU_MD_API_URL", "http://10.89.1.235:8010")
DOCUMENT_CONVERT_URL = os.getenv("DOCUMENT_CONVERT_URL", "http://10.89.31.94:8009/convert")
COMPARE_PARSE_TIMEOUT = int(os.getenv("COMPARE_PARSE_TIMEOUT", "600"))
COMPARE_POLL_INTERVAL = int(os.getenv("COMPARE_POLL_INTERVAL", "2"))
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")

COLORS = {
    'modified': (1, 0.85, 0),
    'deleted': (1, 0.3, 0.3),
    'added': (0.3, 0.8, 0.3),
    'signature': (0.3, 0.5, 1),
    'extra': (0.6, 0.3, 0.8),
}

app = FastAPI(title="Document Compare API")
CONVERT_TO_PDF_EXTS = {".doc", ".docx", ".xls", ".xlsx", ".csv"}
COMPARE_UPLOAD_EXTS = {".pdf"} | CONVERT_TO_PDF_EXTS
TABLE_EXTS = {".xls", ".xlsx", ".csv"}
COMPARE_MODES = {"contract", "document", "table"}
COMPARE_JOBS = {}
COMPARE_JOBS_LOCK = asyncio.Lock()


@app.get("/", response_class=HTMLResponse)
async def index():
    """返回文档对比页面。"""
    with open("templates/index.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/health")
async def health():
    """健康检查接口。"""
    return {"status": "ok"}


@app.post("/compare")
async def compare_alias(
    file_before: UploadFile = File(...),
    file_after: UploadFile = File(...),
    user_id: str = Form("contract_compare"),
    compare_mode: str = Form("contract"),
):
    """兼容旧前端的文档对比接口。"""
    return await compare_contract(file_before, file_after, user_id, compare_mode)


@app.post("/compare-contract")
async def compare_contract(
    file_before: UploadFile = File(...),
    file_after: UploadFile = File(...),
    user_id: str = Form("contract_compare"),
    compare_mode: str = Form("contract"),
):
    """上传两份文档，调用 MinerU 解析接口后执行结构化对比并返回高亮图片。"""
    if not file_before.filename or not file_after.filename:
        raise HTTPException(status_code=400, detail="missing compare files")
    compare_mode = normalize_compare_mode(compare_mode)

    temp_dir = tempfile.mkdtemp(prefix="contract_compare_")
    before_path = os.path.join(temp_dir, safe_filename(file_before.filename))
    after_path = os.path.join(temp_dir, safe_filename(file_after.filename))
    write_upload_file(before_path, await file_before.read())
    write_upload_file(after_path, await file_after.read())

    task_id = new_compare_task_id()
    await set_compare_job(task_id, {
        "task_id": task_id,
        "status": "queued",
        "progress": 0,
        "message": "任务已提交，等待对比",
        "compare_mode": compare_mode,
        "user_id": user_id,
        "before_filename": file_before.filename,
        "after_filename": file_after.filename,
        "created_at": now_text(),
        "updated_at": now_text(),
        "result": None,
        "error": None,
    })
    asyncio.create_task(run_compare_job_async(task_id, before_path, after_path, user_id, compare_mode, temp_dir))
    return await public_compare_status(task_id)


@app.get("/compare/{task_id}")
async def get_compare_status(task_id: str):
    if not await get_compare_job(task_id):
        raise HTTPException(status_code=404, detail="compare task not found")
    return await public_compare_status(task_id)


async def run_compare_job_async(task_id: str, before_path: str, after_path: str, user_id: str, compare_mode: str, temp_dir: str) -> None:
    try:
        await update_compare_job(task_id, status="running", progress=10, message="开始对比")
        result = await asyncio.to_thread(execute_compare_job, before_path, after_path, user_id, compare_mode, temp_dir, task_id)
        await update_compare_job(task_id, status="done", progress=100, message="done", result=result, error=None)
    except Exception as e:
        await update_compare_job(task_id, status="failed", progress=100, message="failed", error=str(e))
    finally:
        await asyncio.to_thread(shutil.rmtree, temp_dir, True)


def execute_compare_job(before_path: str, after_path: str, user_id: str, compare_mode: str, temp_dir: str, task_id: str = "") -> dict:
    if compare_mode == "table":
        table_result = compare_table_files(before_path, after_path, temp_dir)
        return {
            "compare_task_id": task_id,
            "compare_mode": compare_mode,
            "diffs": table_result["diffs"],
            "table_result": table_result,
            "before_images": [],
            "after_images": [],
        }

    before_path = prepare_compare_input(before_path)
    after_path = prepare_compare_input(after_path)

    before_result = parse_file_by_mineru_api(before_path, user_id)
    after_result = parse_file_by_mineru_api(after_path, user_id)

    before_layout = download_json(before_result["json_url"])
    after_layout = download_json(after_result["json_url"])

    before_pdf = download_parse_file(before_result["parse_file_url"], temp_dir, "before")
    after_pdf = download_parse_file(after_result["parse_file_url"], temp_dir, "after")

    diffs = run_pipeline(before_layout, after_layout, before_pdf, after_pdf, compare_mode)
    return {
        "compare_task_id": task_id,
        "compare_mode": compare_mode,
        "before_task_id": before_result.get("task_id"),
        "after_task_id": after_result.get("task_id"),
        "before_json_url": before_result.get("json_url"),
        "after_json_url": after_result.get("json_url"),
        "before_parse_file_url": before_result.get("parse_file_url"),
        "after_parse_file_url": after_result.get("parse_file_url"),
        "diffs": diffs,
        "before_images": pdf_to_highlighted_images(before_pdf, diffs, "before"),
        "after_images": pdf_to_highlighted_images(after_pdf, diffs, "after"),
    }


def new_compare_task_id() -> str:
    return time.strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]


def now_text() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


async def set_compare_job(task_id: str, job: dict) -> None:
    async with COMPARE_JOBS_LOCK:
        COMPARE_JOBS[task_id] = job


async def get_compare_job(task_id: str) -> dict | None:
    async with COMPARE_JOBS_LOCK:
        job = COMPARE_JOBS.get(task_id)
        return dict(job) if job else None


async def update_compare_job(task_id: str, **updates) -> None:
    async with COMPARE_JOBS_LOCK:
        job = COMPARE_JOBS.get(task_id)
        if not job:
            return
        job.update(updates)
        job["updated_at"] = now_text()


async def public_compare_status(task_id: str) -> dict:
    job = await get_compare_job(task_id)
    if not job:
        raise HTTPException(status_code=404, detail="compare task not found")
    response = {
        "task_id": task_id,
        "compare_task_id": task_id,
        "status": job.get("status"),
        "progress": job.get("progress", 0),
        "message": job.get("message", ""),
        "compare_mode": job.get("compare_mode"),
        "user_id": job.get("user_id"),
        "before_filename": job.get("before_filename"),
        "after_filename": job.get("after_filename"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "error": job.get("error"),
    }
    if job.get("status") == "done" and isinstance(job.get("result"), dict):
        response.update(job["result"])
    return response


def parse_file_by_mineru_api(file_path: str, user_id: str) -> dict:
    """提交单个文件到 8010 解析接口，等待完成后返回解析结果。"""
    task_id = submit_parse_task(file_path, user_id)
    result = wait_parse_done(task_id)
    if not result.get("json_url"):
        raise RuntimeError(f"parse task missing json_url: {task_id}")
    if not result.get("parse_file_url"):
        raise RuntimeError(f"parse task missing parse_file_url: {task_id}")
    return result


def normalize_compare_mode(compare_mode: str) -> str:
    mode = (compare_mode or "contract").strip().lower()
    if mode not in COMPARE_MODES:
        raise HTTPException(status_code=400, detail=f"unsupported compare_mode: {compare_mode}")
    return mode


def prepare_compare_input(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in COMPARE_UPLOAD_EXTS:
        raise HTTPException(status_code=400, detail=f"unsupported compare file type: {ext or 'unknown'}")
    if ext in CONVERT_TO_PDF_EXTS:
        return convert_input_to_pdf(file_path)
    return file_path


def compare_table_files(before_path: str, after_path: str, temp_dir: str) -> dict:
    before_ext = os.path.splitext(before_path)[1].lower()
    after_ext = os.path.splitext(after_path)[1].lower()
    if before_ext not in TABLE_EXTS or after_ext not in TABLE_EXTS:
        raise HTTPException(status_code=400, detail="table mode only supports xls, xlsx, csv")

    before_table_path = prepare_table_input(before_path, temp_dir, "before")
    after_table_path = prepare_table_input(after_path, temp_dir, "after")
    before_book = read_table_file(before_table_path)
    after_book = read_table_file(after_table_path)
    sheet_name = choose_sheet_name(before_book, after_book)
    before_rows = before_book.get(sheet_name) or first_sheet_rows(before_book)
    after_rows = after_book.get(sheet_name) or first_sheet_rows(after_book)
    diffs = compare_table_rows(before_rows, after_rows, sheet_name)
    return {
        "sheet": sheet_name,
        "before_rows": before_rows,
        "after_rows": after_rows,
        "diffs": diffs,
        "before_sheets": list(before_book.keys()),
        "after_sheets": list(after_book.keys()),
    }


def prepare_table_input(file_path: str, temp_dir: str, prefix: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    if ext in {".xlsx", ".csv"}:
        return file_path
    if ext == ".xls":
        return convert_input_to_format(file_path, "xlsx", temp_dir, prefix)
    raise HTTPException(status_code=400, detail=f"unsupported table file type: {ext or 'unknown'}")


def read_table_file(file_path: str) -> dict:
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".csv":
        return {"Sheet1": read_csv_rows(file_path)}
    if ext == ".xlsx":
        return read_xlsx_rows(file_path)
    raise RuntimeError(f"unsupported table file type: {ext}")


def read_csv_rows(file_path: str) -> list:
    text = read_text_file(file_path)
    return [[cell.strip() for cell in row] for row in csv.reader(text.splitlines())]


def read_text_file(file_path: str) -> str:
    data = read_bytes_file(file_path)
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def read_bytes_file(file_path: str) -> bytes:
    with open(file_path, "rb") as f:
        return f.read()


def read_xlsx_rows(file_path: str) -> dict:
    ns = {
        "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
        "officeRel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    }
    with zipfile.ZipFile(file_path) as zf:
        shared = read_xlsx_shared_strings(zf, ns)
        styles = read_xlsx_styles(zf, ns)
        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        rel_targets = {rel.attrib.get("Id"): rel.attrib.get("Target", "") for rel in rels}
        sheets = {}
        for sheet in workbook.findall(".//main:sheet", ns):
            name = sheet.attrib.get("name") or "Sheet"
            rel_id = sheet.attrib.get(f"{{{ns['officeRel']}}}id")
            target = rel_targets.get(rel_id, "")
            if not target:
                continue
            path = "xl/" + target.lstrip("/")
            if path not in zf.namelist():
                path = "xl/worksheets/" + os.path.basename(target)
            if path in zf.namelist():
                sheets[name] = read_xlsx_sheet(zf.read(path), shared, styles, ns)
        return sheets or {"Sheet1": []}


def read_xlsx_shared_strings(zf: zipfile.ZipFile, ns: dict) -> list:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    values = []
    for si in root.findall("main:si", ns):
        parts = [node.text or "" for node in si.findall(".//main:t", ns)]
        values.append("".join(parts))
    return values


def read_xlsx_styles(zf: zipfile.ZipFile, ns: dict) -> list:
    if "xl/styles.xml" not in zf.namelist():
        return []
    builtins = {
        "0": "General", "1": "0", "2": "0.00", "3": "#,##0", "4": "#,##0.00",
        "9": "0%", "10": "0.00%", "11": "0.00E+00", "14": "m/d/yy",
    }
    root = ET.fromstring(zf.read("xl/styles.xml"))
    custom = {}
    for fmt in root.findall(".//main:numFmt", ns):
        fmt_id = fmt.attrib.get("numFmtId")
        code = fmt.attrib.get("formatCode")
        if fmt_id and code:
            custom[fmt_id] = code
    styles = []
    for xf in root.findall(".//main:cellXfs/main:xf", ns):
        fmt_id = xf.attrib.get("numFmtId", "0")
        styles.append(custom.get(fmt_id) or builtins.get(fmt_id, "General"))
    return styles


def read_xlsx_sheet(data: bytes, shared: list, styles: list, ns: dict) -> list:
    root = ET.fromstring(data)
    rows = []
    for row in root.findall(".//main:row", ns):
        values = []
        for cell in row.findall("main:c", ns):
            col_index = xlsx_col_index(cell.attrib.get("r", ""))
            while len(values) < col_index:
                values.append("")
            values.append(read_xlsx_cell(cell, shared, styles, ns))
        rows.append(values)
    return trim_empty_rows(rows)


def read_xlsx_cell(cell, shared: list, styles: list, ns: dict) -> str:
    cell_type = cell.attrib.get("t", "")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//main:t", ns)).strip()
    value = cell.find("main:v", ns)
    raw = value.text if value is not None and value.text is not None else ""
    if cell_type == "s":
        try:
            return shared[int(raw)].strip()
        except (ValueError, IndexError):
            return raw.strip()
    style_id = cell.attrib.get("s")
    style = styles[int(style_id)] if style_id and style_id.isdigit() and int(style_id) < len(styles) else "General"
    return format_xlsx_value(raw.strip(), style)


def format_xlsx_value(raw: str, style: str) -> str:
    if raw == "":
        return ""
    number = parse_decimal(raw)
    if number is None:
        return raw
    style = clean_excel_format(style or "General")
    if is_date_format(style):
        return raw
    if style.lower() == "general":
        return format_general_number(number)
    percent = "%" in style
    if percent:
        number *= Decimal("100")
    decimal_places = excel_decimal_places(style)
    use_grouping = "," in style.split(".", 1)[0]
    value = quantize_decimal(number, decimal_places)
    text = f"{value:,.{decimal_places}f}" if use_grouping else f"{value:.{decimal_places}f}"
    if decimal_places > 0 and decimal_part_is_optional(style):
        text = text.rstrip("0").rstrip(".")
    return text + ("%" if percent else "")


def parse_decimal(value: str) -> Decimal | None:
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def clean_excel_format(style: str) -> str:
    style = style.split(";", 1)[0]
    style = re.sub(r'"[^"]*"', "", style)
    style = re.sub(r"\[[^\]]+\]", "", style)
    style = style.replace("\\", "")
    return style.strip() or "General"


def is_date_format(style: str) -> bool:
    lowered = style.lower()
    return any(token in lowered for token in ("yy", "dd", "hh", "ss")) or bool(re.search(r"(^|[^a-z])m{1,5}([^a-z]|$)", lowered))


def excel_decimal_places(style: str) -> int:
    if "." not in style:
        return 0
    decimal_part = style.split(".", 1)[1]
    decimal_part = decimal_part.split("%", 1)[0]
    return len(re.findall(r"[0#?]", decimal_part))


def decimal_part_is_optional(style: str) -> bool:
    if "." not in style:
        return False
    decimal_part = style.split(".", 1)[1].split("%", 1)[0]
    return "0" not in decimal_part


def quantize_decimal(value: Decimal, places: int) -> Decimal:
    unit = Decimal("1") if places <= 0 else Decimal("1").scaleb(-places)
    return value.quantize(unit, rounding=ROUND_HALF_UP)


def format_general_number(value: Decimal) -> str:
    if value and value.adjusted() >= -12:
        significant_places = max(0, 12 - value.adjusted() - 1)
        value = quantize_decimal(value, significant_places)
    value = value.normalize()
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def xlsx_col_index(ref: str) -> int:
    letters = re.sub(r"[^A-Z]", "", (ref or "").upper())
    index = 0
    for ch in letters:
        index = index * 26 + ord(ch) - 64
    return max(index - 1, 0)


def trim_empty_rows(rows: list) -> list:
    while rows and not any(str(cell).strip() for cell in rows[-1]):
        rows.pop()
    width = max((len(row) for row in rows), default=0)
    return [row + [""] * (width - len(row)) for row in rows]


def choose_sheet_name(before_book: dict, after_book: dict) -> str:
    for name in before_book:
        if name in after_book:
            return name
    return next(iter(before_book or after_book or {"Sheet1": []}))


def first_sheet_rows(book: dict) -> list:
    return next(iter(book.values()), [])


def compare_table_rows(before_rows: list, after_rows: list, sheet_name: str) -> list:
    before_keys = [normalize_row(row) for row in before_rows]
    after_keys = [normalize_row(row) for row in after_rows]
    matcher = difflib.SequenceMatcher(None, before_keys, after_keys)
    diffs = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "delete":
            for row_index in range(i1, i2):
                diffs.append(table_row_diff("table_deleted", sheet_name, row_index, None, before_rows[row_index], []))
        elif tag == "insert":
            for row_index in range(j1, j2):
                diffs.append(table_row_diff("table_added", sheet_name, None, row_index, [], after_rows[row_index]))
        else:
            pair_count = min(i2 - i1, j2 - j1)
            for offset in range(pair_count):
                diffs.extend(compare_table_cells(before_rows[i1 + offset], after_rows[j1 + offset], sheet_name, i1 + offset, j1 + offset))
            for row_index in range(i1 + pair_count, i2):
                diffs.append(table_row_diff("table_deleted", sheet_name, row_index, None, before_rows[row_index], []))
            for row_index in range(j1 + pair_count, j2):
                diffs.append(table_row_diff("table_added", sheet_name, None, row_index, [], after_rows[row_index]))
    return diffs


def normalize_row(row: list) -> str:
    return "\u241f".join(normalize_cell(cell) for cell in row)


def normalize_cell(value) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def compare_table_cells(before_row: list, after_row: list, sheet_name: str, before_row_index: int, after_row_index: int) -> list:
    diffs = []
    width = max(len(before_row), len(after_row))
    for col in range(width):
        old = before_row[col] if col < len(before_row) else ""
        new = after_row[col] if col < len(after_row) else ""
        if normalize_cell(old) == normalize_cell(new):
            continue
        if str(old).strip() and str(new).strip():
            diff_type = "table_modified"
        elif str(new).strip():
            diff_type = "table_added"
        else:
            diff_type = "table_deleted"
        diffs.append({
            "type": diff_type,
            "sheet": sheet_name,
            "before_row": before_row_index,
            "after_row": after_row_index,
            "col": col,
            "old_text": str(old),
            "new_text": str(new),
            "text": f"{excel_cell_name(after_row_index if diff_type != 'table_deleted' else before_row_index, col)}: {old} -> {new}",
        })
    return diffs


def table_row_diff(diff_type: str, sheet_name: str, before_row: int | None, after_row: int | None, old_row: list, new_row: list) -> dict:
    row_index = after_row if after_row is not None else before_row
    return {
        "type": diff_type,
        "sheet": sheet_name,
        "before_row": before_row,
        "after_row": after_row,
        "row": row_index,
        "old_text": " | ".join(str(cell) for cell in old_row),
        "new_text": " | ".join(str(cell) for cell in new_row),
        "text": f"row {(row_index or 0) + 1}",
    }


def excel_cell_name(row: int, col: int) -> str:
    col += 1
    name = ""
    while col:
        col, rem = divmod(col - 1, 26)
        name = chr(65 + rem) + name
    return f"{name}{row + 1}"


def convert_input_to_pdf(file_path: str) -> str:
    return convert_input_to_format(file_path, "pdf")


def convert_input_to_format(file_path: str, output_format: str, output_dir: str | None = None, prefix: str | None = None) -> str:
    output_format = output_format.lower().strip().lstrip(".")
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    output_dir = output_dir or os.path.dirname(file_path)
    name_prefix = prefix or base_name
    output_path = os.path.join(output_dir, f"{name_prefix}_{uuid.uuid4().hex[:8]}.{output_format}")
    with open(file_path, "rb") as f:
        files = {"file": (converter_upload_filename(file_path), f)}
        data = {"output_format": output_format}
        resp = request_post(DOCUMENT_CONVERT_URL, files=files, data=data, timeout=300)
    if resp.status_code != 200:
        raise RuntimeError(f"convert input to {output_format} failed: {resp.status_code} {resp.text[:300]}")
    converted_data = extract_converted_file(resp, output_format)
    with open(output_path, "wb") as f:
        f.write(converted_data)
    return output_path


def extract_converted_pdf(resp: requests.Response) -> bytes:
    return extract_converted_file(resp, "pdf")


def extract_converted_file(resp: requests.Response, output_format: str) -> bytes:
    output_format = output_format.lower().strip().lstrip(".")
    if resp.content.startswith(b"%PDF"):
        return resp.content
    if output_format in {"xlsx", "pptx"} and resp.content.startswith(b"PK"):
        return resp.content
    content_type = resp.headers.get("content-type", "").lower()
    if "json" not in content_type:
        raise RuntimeError(f"convert input to {output_format} returned unexpected content: {content_type or 'unknown'}")
    file_url = find_converted_file_url(resp.json(), output_format)
    if not file_url:
        raise RuntimeError(f"convert input to {output_format} JSON missing file url")
    file_resp = request_get(file_url, timeout=300)
    if file_resp.status_code != 200:
        raise RuntimeError(f"download converted {output_format} failed: {file_resp.status_code} {file_resp.text[:300]}")
    return file_resp.content


def find_pdf_url(value) -> str:
    return find_converted_file_url(value, "pdf")


def find_converted_file_url(value, output_format: str) -> str:
    if isinstance(value, dict):
        for key in ("file_url", "fileUrl", "download_url", "downloadUrl", "url", f"{output_format}_url", f"{output_format}Url"):
            item = normalize_file_reference(value.get(key), output_format)
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
        return normalize_file_reference(value, output_format)
    return ""


def normalize_pdf_reference(value) -> str:
    return normalize_file_reference(value, "pdf")


def normalize_file_reference(value, output_format: str) -> str:
    if not isinstance(value, str):
        return ""
    suffix = f".{output_format.lower().strip().lstrip('.')}"
    parsed = urlparse(value.strip())
    return value.strip() if parsed.scheme in {"http", "https"} and parsed.netloc and parsed.path.lower().endswith(suffix) else ""


def converter_upload_filename(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower() or ".bin"
    return f"input_{uuid.uuid4().hex[:8]}{ext}"


def request_post(url: str, **kwargs) -> requests.Response:
    session = requests.Session()
    session.trust_env = False
    try:
        return session.post(url, **kwargs)
    finally:
        session.close()


def request_get(url: str, **kwargs) -> requests.Response:
    session = requests.Session()
    session.trust_env = False
    try:
        return session.get(url, **kwargs)
    finally:
        session.close()


def submit_parse_task(file_path: str, user_id: str) -> str:
    """调用 /parse-md 提交异步解析任务。"""
    with open(file_path, "rb") as f:
        resp = requests.post(
            f"{MINERU_MD_API_URL.rstrip('/')}/parse-md",
            files={"file": (os.path.basename(file_path), f)},
            data={"user_id": user_id},
            timeout=60,
        )
    resp.raise_for_status()
    data = resp.json()
    task_id = data.get("task_id")
    if not task_id:
        raise RuntimeError(f"parse api did not return task_id: {data}")
    return task_id


def wait_parse_done(task_id: str) -> dict:
    """轮询 /parse-md/{task_id}，直到解析完成或失败。"""
    started = time.time()
    while time.time() - started < COMPARE_PARSE_TIMEOUT:
        resp = requests.get(f"{MINERU_MD_API_URL.rstrip('/')}/parse-md/{task_id}", timeout=30)
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status")
        if status == "done":
            return data
        if status == "failed":
            raise RuntimeError(data.get("error") or f"parse failed: {task_id}")
        time.sleep(COMPARE_POLL_INTERVAL)
    raise TimeoutError(f"parse timeout: {task_id}")


def download_json(url: str) -> dict:
    """下载 MinerU layout JSON。"""
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    return resp.json()


def download_parse_file(url: str, output_dir: str, prefix: str) -> str:
    """下载真正送进 MinerU 的文件，供 PyMuPDF 画框使用。"""
    parsed = urlparse(url)
    suffix = os.path.splitext(parsed.path)[1] or ".pdf"
    path = os.path.join(output_dir, f"{prefix}{suffix}")
    resp = requests.get(url, timeout=300)
    resp.raise_for_status()
    with open(path, "wb") as f:
        f.write(resp.content)
    return path


def write_upload_file(path: str, data: bytes) -> None:
    with open(path, "wb") as f:
        f.write(data)


def safe_filename(value: str) -> str:
    value = os.path.basename(value or "file")
    return "".join(ch if ch.isalnum() or ch in "._-()" else "_" for ch in value) or "file"

def extract_text(block: dict) -> str:
    texts = []
    if 'text' in block:
        t = block['text']
        texts.append(t if isinstance(t, str) else ' '.join(str(x) for x in t))
    for line in block.get('lines', []):
        for span in line.get('spans', []):
            if span.get('content'): texts.append(span['content'])
            if span.get('html'): texts.append(re.sub(r'<[^>]+>', ' ', span['html']))
    for sub in block.get('blocks', []): texts.append(extract_text(sub))
    return ' '.join(str(t) for t in texts).strip()

def flatten_layout(layout: dict) -> list:
    seen = set()
    blocks = []
    for page in layout.get('pdf_info', []):
        page_no = page.get('page_idx', 0)
        for key in ['para_blocks', 'preproc_blocks']:
            for block in page.get(key, []):
                btype, bbox = block.get('type', 'text'), block.get('bbox', [0,0,0,0])
                if btype == 'list' and 'blocks' in block:
                    for sub in block['blocks']:
                        text, sb = extract_text(sub).strip(), sub.get('bbox', bbox)
                        if text and (page_no, tuple(sb), text[:100]) not in seen:
                            seen.add((page_no, tuple(sb), text[:100]))
                            blocks.append({'page':page_no,'y':sb[1] if len(sb)>=2 else 0,'type':sub.get('type','text'),'text':text,'bbox':sb,'_raw':sub})
                    continue
                if btype == 'table' and 'blocks' in block:
                    for sub in block['blocks']:
                        text, sb = extract_text(sub).strip(), sub.get('bbox', bbox)
                        if text and (page_no, tuple(sb), text[:100]) not in seen:
                            seen.add((page_no, tuple(sb), text[:100]))
                            blocks.append({'page':page_no,'y':sb[1] if len(sb)>=2 else 0,'type':'table_'+sub.get('type','text'),'text':text,'bbox':sb,'_raw':sub})
                    continue
                text = extract_text(block).strip()
                if text and (page_no, tuple(bbox), text[:100]) not in seen:
                    seen.add((page_no, tuple(bbox), text[:100]))
                    blocks.append({'page':page_no,'y':bbox[1] if len(bbox)>=2 else 0,'type':btype,'text':text,'bbox':bbox,'_raw':block})
    blocks.sort(key=lambda x: (x['page'], x['y']))
    return blocks

def normalize(text: str) -> str:
    return re.sub(r'\s+','',text).replace('_','').replace('·','-').replace('•','-').replace('（','(').replace('）',')').replace('：',':').replace('，',',').replace('。','.').replace('；',';').lower()

def compare_blocks(before: list, after: list) -> dict:
    if not before or not after: 
        return {'modified':[],'deleted':[],'added':[],'has_diff':False}
    
    bn = [normalize(b['text']) for b in before]
    an = [normalize(a['text']) for a in after]
    matcher = difflib.SequenceMatcher(None, bn, an)
    
    modified, deleted, added = [], [], []
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            continue
        
        elif tag == 'delete':
            for i in range(i1, i2):
                deleted.append(before[i])
        
        elif tag == 'insert':
            for j in range(j1, j2):
                added.append(after[j])
        
        elif tag == 'replace':
            # 先合并两边所有块，看是否一致
            b_merged = normalize(''.join(b['text'] for b in before[i1:i2]))
            a_merged = normalize(''.join(a['text'] for a in after[j1:j2]))
            
            if b_merged == a_merged:
                # 合并后一致 → 段落拆分差异，跳过
                continue
            
            # 不一致 → 逐个对比
            for k in range(min(i2-i1, j2-j1)):
                if bn[i1+k] != an[j1+k]:
                    modified.append({
                        'old_text': before[i1+k]['text'],
                        'new_text': after[j1+k]['text'],
                        'old_bbox': before[i1+k].get('bbox', []),
                        'new_bbox': after[j1+k].get('bbox', []),
                        'page': before[i1+k]['page']
                    })
            
            # 多余的
            for i in range(i1 + min(i2-i1, j2-j1), i2):
                deleted.append(before[i])
            for j in range(j1 + min(i2-i1, j2-j1), j2):
                added.append(after[j])
    
    return {
        'modified': modified,
        'deleted': deleted,
        'added': added,
        'has_diff': len(modified)+len(deleted)+len(added) > 0
    }

def find_signature_region(before_blocks: list, after_blocks: list) -> dict:
    table_idx = None
    for i,b in enumerate(before_blocks):
        if 'table' in b.get('type',''): table_idx=i; break
    if table_idx is None: return None
    ab, aa = None, None
    for i in range(table_idx-1,-1,-1):
        if 'table' not in before_blocks[i].get('type',''): ab=before_blocks[i]['text'][:30]; break
    for i in range(table_idx+1,len(before_blocks)):
        if 'table' not in before_blocks[i].get('type',''): aa=before_blocks[i]['text'][:30]; break
    if not ab or not aa: return None
    bboxes=[]
    for i in range(table_idx,len(before_blocks)):
        if 'table' in before_blocks[i].get('type',''): bboxes.append(before_blocks[i]['bbox'])
        else: break
    bm=[min(b[0]for b in bboxes),min(b[1]for b in bboxes),max(b[2]for b in bboxes),max(b[3]for b in bboxes)]
    si,ei=None,None
    for i,b in enumerate(after_blocks):
        sb=difflib.SequenceMatcher(None,b['text'][:30],ab).ratio()
        sa=difflib.SequenceMatcher(None,b['text'][:30],aa).ratio()
        if sb>0.6 and si is None: si=i+1
        if sa>0.6 and si is not None: ei=i; break
    if si is None or ei is None or si>ei: return None
    region=after_blocks[si:ei]
    if not region: return None
    am=[min(b['bbox'][0]for b in region),min(b['bbox'][1]for b in region),max(b['bbox'][2]for b in region),max(b['bbox'][3]for b in region)]
    return {'page_before':before_blocks[table_idx]['page'],'page_after':region[0]['page'],'before_bbox':bm,'after_bbox':am,'before_table_start':table_idx,'before_table_end':table_idx+len(bboxes),'sig_start':si,'sig_end':ei,'before_table_blocks':before_blocks[table_idx:table_idx+len(bboxes)],'after_region_blocks':region}

def extract_table_fields(before_table_blocks: list) -> list:
    fields = []
    for block in before_table_blocks:
        for line in block.get('_raw',{}).get('lines',[]):
            for span in line.get('spans',[]):
                html = span.get('html','')
                if html:
                    td = re.sub(r'<[^>]+>',' ',html); td = re.sub(r'\s+',' ',td).strip()
                    for p in td.split(':'):
                        p=p.strip()
                        if p and not re.match(r'^\d',p): fields.append(p)
    return fields

def call_deepseek(prompt: str) -> str:
    try:
        resp = requests.post("https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization":f"Bearer {DEEPSEEK_API_KEY}","Content-Type":"application/json"},
            json={"model":"deepseek-chat","messages":[{"role":"user","content":prompt}],"temperature":0,"max_tokens":200},timeout=30)
        return resp.json()["choices"][0]["message"]["content"]
    except: return '{"filled":false}'

def check_signature_by_agent(before_table_blocks: list, after_region_blocks: list) -> bool:
    fields = extract_table_fields(before_table_blocks)
    if not fields: return False
    after_text = ' '.join(b['text'] for b in after_region_blocks)
    prompt = f"""判断签署区域字段是否已填写。字段：{json.dumps(fields,ensure_ascii=False)}。内容：{after_text}。只返回JSON：{{"filled":true/false,"empty_fields":[],"summary":""}}"""
    try:
        content = call_deepseek(prompt).strip()
        if content.startswith("```"): content = content.split("\n",1)[1].split("```")[0]
        return not json.loads(content).get('filled',True)
    except: return False

def find_extra_content(before_blocks: list, after_blocks: list) -> dict:
    if not before_blocks or not after_blocks: return None
    anchor = before_blocks[-1]['text'][:40]
    si = None
    for i,b in enumerate(after_blocks):
        if difflib.SequenceMatcher(None,b['text'][:40],anchor).ratio()>0.6: si=i+1; break
    if si is None or si>=len(after_blocks): return None
    extra = after_blocks[si:]
    if not extra: return None
    bboxes = [b['bbox'] for b in extra]
    return {'page':extra[0]['page'],'merged_bbox':[min(b[0]for b in bboxes),min(b[1]for b in bboxes),max(b[2]for b in bboxes),max(b[3]for b in bboxes)]}

def is_bbox_overlap(bbox1, bbox2):
    if not bbox1 or not bbox2 or len(bbox1)!=4 or len(bbox2)!=4: return False
    return not (bbox1[2]<bbox2[0] or bbox2[2]<bbox1[0] or bbox1[3]<bbox2[1] or bbox2[3]<bbox1[1])

def verify_diff_with_qwen(pdf_before: str, pdf_after: str, diff: dict) -> bool:
    try:
        print(f"      old: {diff['old_text'][:60]}")
        print(f"      new: {diff['new_text'][:60]}")
        doc_b = fitz.open(pdf_before); doc_a = fitz.open(pdf_after)
        page = diff['page']
        def capture(doc, bbox):
            rect = fitz.Rect(*bbox)
            rect = fitz.Rect(max(0,rect[0]-15),max(0,rect[1]-15),rect[2]+15,rect[3]+15)
            pix = doc[page].get_pixmap(clip=rect, matrix=fitz.Matrix(2,2))
            return base64.b64encode(pix.tobytes("png")).decode()
        img_old = capture(doc_b, diff['old_bbox']); img_new = capture(doc_a, diff['new_bbox'])
        doc_b.close(); doc_a.close()
        resp = requests.post(
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            headers={"Authorization":f"Bearer {QWEN_API_KEY}","Content-Type":"application/json"},
            json={"model":"qwen3.5-omni-plus-2026-03-15","messages":[{"role":"user","content":[
                {"type":"image_url","image_url":{"url":f"data:image/png;base64,{img_old}"}},
                {"type":"image_url","image_url":{"url":f"data:image/png;base64,{img_new}"}},
                {"type":"text","text":"对比两张文档局部截图，判断内容是否实质一致。忽略盖章/签名/格式变化。只返回JSON：{\"has_diff\":true/false}"}
            ]}],"max_tokens":50},timeout=30)
        content = resp.json()['choices'][0]['message']['content']
        if content.startswith("```"): content = content.split("\n",1)[1].split("```")[0]
        return json.loads(content).get('has_diff', True)
    except Exception as e:
        print(f"   ⚠️ 千问验证失败: {e}")
        return True

def run_pipeline(layout_before: dict, layout_after: dict, pdf_before: str, pdf_after: str, compare_mode: str = "contract") -> list:
    bb = flatten_layout(layout_before); ab = flatten_layout(layout_after)
    print(f"   盖章前: {len(bb)} 块, 盖章后: {len(ab)} 块")
    use_contract_rules = compare_mode == "contract"
    sig = find_signature_region(bb, ab) if use_contract_rules else None
    shd = False
    if sig:
        print(f"   签署区域: 盖章前第{sig['page_before']+1}页, 盖章后第{sig['page_after']+1}页")
        shd = check_signature_by_agent(sig['before_table_blocks'], sig['after_region_blocks'])
        bbody = bb[:sig['before_table_start']] + bb[sig['before_table_end']:]
        abody = ab[:sig['sig_start']] + ab[sig['sig_end']:]
    else:
        bbody, abody = bb, ab
    diff = compare_blocks(bbody, abody)
    print(f"   候选修改: {len(diff['modified'])} 处")
    extra = find_extra_content(bbody, abody) if use_contract_rules else None
    extra_bbox = extra['merged_bbox'] if extra else None
    diffs = []
    for i, m in enumerate(diff['modified']):
        if not (m.get('old_bbox') and len(m['old_bbox'])==4 and m.get('new_bbox') and len(m['new_bbox'])==4): continue
        print(f"   🤖 Agent验证 [{i+1}/{len(diff['modified'])}]...")
        if True:
            print(f"      🚨 确认差异: {m['old_text'][:40]}")
            diffs.append({'type':'modified','page':m['page'],'old_text':m['old_text'],'new_text':m['new_text'],'old_bbox':m['old_bbox'],'new_bbox':m['new_bbox']})
        else:
            print(f"      ✅ 过滤误报: {m['old_text'][:40]}")
    for d in diff['deleted']:
        if d.get('bbox') and len(d['bbox'])==4:
            if extra_bbox and is_bbox_overlap(d['bbox'], extra_bbox): continue
            diffs.append({'type':'deleted','page':d['page'],'text':d['text'],'bbox':d['bbox']})
    for a in diff['added']:
        if a.get('bbox') and len(a['bbox'])==4:
            if extra_bbox and is_bbox_overlap(a['bbox'], extra_bbox): continue
            diffs.append({'type':'added','page':a['page'],'text':a['text'],'bbox':a['bbox']})
    if sig and shd:
        diffs.append({'type':'signature','page':sig['page_after'],'before_bbox':sig['before_bbox'],'after_bbox':sig['after_bbox']})
    if extra:
        diffs.append({'type':'extra','page':extra['page'],'bbox':extra['merged_bbox']})
    print(f"   最终差异: {len(diffs)} 处")
    return diffs

def pdf_to_highlighted_images(pdf_path: str, diffs: list, side: str) -> list:
    doc = fitz.open(pdf_path)
    for diff in diffs:
        page = diff.get('page', 0)
        if page >= len(doc): continue
        bbox = None
        if diff['type']=='modified': bbox = diff.get('new_bbox') if side=='after' else diff.get('old_bbox')
        elif diff['type']=='deleted' and side=='before': bbox = diff.get('bbox')
        elif diff['type']=='added' and side=='after': bbox = diff.get('bbox')
        elif diff['type']=='signature': bbox = diff.get('after_bbox') if side=='after' else diff.get('before_bbox')
        elif diff['type']=='extra' and side=='after': bbox = diff.get('bbox')
        if not bbox or len(bbox)!=4: continue
        doc[page].draw_rect(fitz.Rect(*bbox), color=COLORS.get(diff['type'],(1,0.85,0)), fill=COLORS.get(diff['type'],(1,0.85,0)), width=2, fill_opacity=0.35)
    images = []
    for page in doc:
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5,1.5))
        images.append(base64.b64encode(pix.tobytes("png")).decode())
    doc.close()
    return images

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8020)
