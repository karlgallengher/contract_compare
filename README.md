# MinerU Markdown API

这是一个独立的 MinerU 解析接口服务，只负责把上传文件解析成 Markdown，并把结果文件保存到 MinIO。

主服务文件：

```text
mineru_md_api.py
```

默认端口：

```text
8010
```

## 功能

接口提供异步解析能力：

```text
上传文件 -> 返回 task_id
后台解析 -> 保存结果到 MinIO
查询 task_id -> 返回解析状态和结果 URL
```

解析完成后会返回：

```text
markdown_url       result.md 固定访问地址
json_url           result.json 固定访问地址
original_url       原始上传文件固定访问地址
parse_file_url     实际送入 MinerU 的文件固定访问地址
image_urls         图片固定访问地址映射
```

同时保留 MinIO 对象路径字段：

```text
markdown_object
json_object
original_object
parse_file_object
```

`*_url` 用于外部访问，`*_object` 用于后端定位 MinIO 对象。

## 支持文件类型

当前入口只支持：

```text
pdf
docx
pptx
xlsx
csv
txt
md
markdown
```

处理方式：

```text
txt / md / markdown       直接读取原文，保存为 result.md
pdf / docx / pptx / xlsx  直接提交给 MinerU
csv                       先转换为 xlsx，再提交给 MinerU
```

不支持的文件会直接返回 `400 unsupported file type`，不会创建任务。

## MinIO 存储结构

对象路径格式：

```text
{MINIO_PUBLIC_PREFIX}/users/{user_id}/tasks/{task_id}/
```

默认前缀：

```text
mineru
```

示例：

```text
mineru/users/anonymous/tasks/20260701_133303_650f98c0/
  original/
    before.pdf
  converted/
    data_xxxx.xlsx
  images/
    xxx.jpg
  result/
    result.md
    result.json
```

## URL 规则

当前接口返回固定 URL，不返回预签名 URL。

固定 URL 格式：

```text
{MINIO_PUBLIC_BASE_URL}/{MINIO_BUCKET}/{object_name}
```

示例：

```text
https://chat-s3.ecorubbercloud.com/tableau/mineru/users/anonymous/tasks/.../result/result.md
```

图片路径处理：

```text
result.md 中的图片路径会替换为固定 URL
result.json 中的图片路径也会替换为固定 URL
image_urls 字段中的图片地址也是固定 URL
```

## 接口

### 健康检查

```text
GET /health
```

### 提交解析任务

```text
POST /parse-md
```

表单参数：

```text
file     必填，上传文件
user_id  可选，默认 anonymous
```

示例：

```bash
curl -X POST "http://127.0.0.1:8010/parse-md" \
  -F "file=@before.pdf" \
  -F "user_id=anonymous"
```

### 查询任务状态

```text
GET /parse-md/{task_id}
```

状态：

```text
queued   已提交，等待解析
running  正在解析
done     解析完成
failed   解析失败
```

完成后返回字段包括：

```text
task_id
user_id
filename
status
progress
message
error
format
markdown_url
markdown_object
json_url
json_object
original_url
original_object
parse_file_url
parse_file_object
image_urls
image_count
skipped_image_count
```

## 环境变量

必填：

```text
MINIO_ENDPOINT=
MINIO_ACCESS_KEY=
MINIO_SECRET_KEY=
MINIO_BUCKET=
```

常用配置：

```text
MINERU_URL=http://10.89.1.235:7803/file_parse
MINIO_PUBLIC_BASE_URL=https://chat-s3.ecorubbercloud.com
MINIO_PUBLIC_PREFIX=mineru
PARSE_MAX_CONCURRENT_JOBS=4
```

可选配置：

```text
DOCUMENT_CONVERT_URL=http://10.89.16.21:8009/convert
LIBREOFFICE_BIN=libreoffice
MINIO_PRESIGNED_DAYS=7
```

说明：

```text
MINERU_URL                 MinerU 原始解析接口地址
MINIO_ENDPOINT             MinIO API endpoint，不带 http://
MINIO_ACCESS_KEY           MinIO access key
MINIO_SECRET_KEY           MinIO secret key
MINIO_BUCKET               MinIO bucket，例如 tableau
MINIO_PUBLIC_BASE_URL      对外访问 MinIO 文件的固定域名
MINIO_PUBLIC_PREFIX        对象路径前缀，默认 mineru
PARSE_MAX_CONCURRENT_JOBS  后台解析最大并发数
```

`.env` 不要提交到 Git。

## 安装依赖

建议 Python 3.10+。

```bash
python -m venv venv
source venv/bin/activate
pip install fastapi uvicorn python-multipart requests minio urllib3
```

Windows PowerShell：

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install fastapi uvicorn python-multipart requests minio urllib3
```

## 启动服务

```bash
uvicorn mineru_md_api:app --host 0.0.0.0 --port 8010
```

或者：

```bash
python mineru_md_api.py
```

访问文档：

```text
http://127.0.0.1:8010/docs
```

## 调用方约定

调用方不应该依赖接口直接返回 Markdown 原文。

正确方式：

```text
1. POST /parse-md 提交任务
2. GET /parse-md/{task_id} 查询状态
3. status=done 后，从 markdown_url 下载 Markdown
4. 从 json_url 下载 JSON
```

`markdown_url` 和 `json_url` 是固定 URL，不带签名参数。

## 排查

如果 `markdown_url/json_url` 为空：

```text
检查 MINIO_ENDPOINT、MINIO_ACCESS_KEY、MINIO_SECRET_KEY、MINIO_BUCKET 是否完整
```

如果任务失败：

```text
查看返回字段 error
```

如果固定 URL 打不开：

```text
检查 MINIO_PUBLIC_BASE_URL 是否正确
检查调用方网络是否能访问该域名
检查 MinIO 对象是否存在
```

如果中文 TXT 乱码：

```text
当前读取顺序为 utf-8-sig、utf-8、gb18030、gbk
请确认部署的是最新版本
```
