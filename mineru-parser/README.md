# MinerU Parser

独立的 MinerU Markdown 解析服务。

## 功能

- `POST /parse-md`：提交解析任务，立即返回 `task_id`
- `GET /parse-md/{task_id}`：查询任务状态和结果
- 后台异步解析，用户关闭页面后任务仍会继续执行
- 解析结果保存到 MinIO，并返回固定公开 URL
- Markdown 中引用到的图片会上传到 MinIO，未引用图片会跳过
- HTML 表格会转换为原生 Markdown 表格

## 支持类型

```text
pdf
doc
docx
ppt
pptx
xls
xlsx
csv
txt
md
markdown
jpg
jpeg
png
```

## 处理路径

```text
pdf       -> 直接 MinerU，原始 PDF 超过 100 页会 failed
doc       -> 转 PDF，再 MinerU
docx      -> 直接 MinerU
ppt       -> 转 PPTX，再 MinerU
pptx      -> 直接 MinerU
xls       -> 转 XLSX，再 MinerU
xlsx      -> 直接 MinerU
csv       -> 转 XLSX，再 MinerU
txt/md    -> 原文保存为 Markdown
jpg/png   -> hybrid-auto-engine + image_analysis
```

## 启动

```bash
uvicorn mineru_md_api:app --host 0.0.0.0 --port 8010
```

## 关键环境变量

```env
MINERU_URL=http://10.89.1.235:7803/file_parse
DOCUMENT_CONVERT_URL=http://10.89.31.94:8009/convert
MINIO_ENDPOINT=
MINIO_ACCESS_KEY=
MINIO_SECRET_KEY=
MINIO_BUCKET=tableau
MINIO_PUBLIC_BASE_URL=https://chat-s3.ecorubbercloud.com
PARSE_MAX_CONCURRENT_JOBS=4
MINERU_LANG_LIST=ch
```

## 返回状态

```text
queued   已提交，等待执行
running  正在执行
done     完成
failed   失败或被限制拦截
```

## MinIO 路径

```text
mineru/users/{user_id}/tasks/{task_id}/original/{原始文件}
mineru/users/{user_id}/tasks/{task_id}/converted/{转换后文件}
mineru/users/{user_id}/tasks/{task_id}/result/result.md
mineru/users/{user_id}/tasks/{task_id}/result/result.json
mineru/users/{user_id}/tasks/{task_id}/images/{图片名}
```

## 测试

```bash
curl -X POST http://127.0.0.1:8010/parse-md \
  -F "file=@before.pdf" \
  -F "user_id=anonymous"

curl http://127.0.0.1:8010/parse-md/{task_id}
```
