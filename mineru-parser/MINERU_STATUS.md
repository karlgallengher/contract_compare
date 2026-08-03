# MinerU Markdown API 任务状态说明

本文档说明 `mineru_md_api.py` 中异步解析接口的任务状态含义和典型使用场景。

## 接口概览

提交任务：

```http
POST /parse-md
```

查询任务：

```http
GET /parse-md/{task_id}
```

提交成功后接口会立即返回 `task_id`，调用方使用 `task_id` 轮询任务状态。

## 状态列表

| status | 含义 | 典型场景 | 调用方建议 |
| --- | --- | --- | --- |
| `queued` | 已提交，等待执行 | 当前并发任务已满，新任务进入等待队列 | 显示“排队中”，继续轮询 |
| `running` | 正在执行 | 文件准备、转换、调用 MinerU、上传图片、保存结果中 | 显示进度和 message，继续轮询 |
| `done` | 解析成功 | Markdown 已生成，图片路径已替换，`result.md` 已保存到 MinIO | 读取 `markdown_url` 或 `markdown_object` |
| `failed` | 解析失败 | 文件类型不支持、转换失败、MinerU 失败、MinIO 上传失败等 | 显示 `error`，允许用户重试 |

## progress 阶段

`progress` 是一个粗略进度值，用来辅助前端展示，不代表精确耗时比例。

| progress | message | 含义 |
| --- | --- | --- |
| `0` | `queued` | 任务已提交，等待并发名额 |
| `10` | `started` | 任务开始执行 |
| `20` | `preparing file` | 准备输入文件；不支持格式会在这里转 PDF |
| `35` | `calling MinerU` | 正在调用 MinerU 解析 |
| `70` | `uploading images` | 正在上传 Markdown 引用到的图片 |
| `85` | `replacing image paths` | 正在把 Markdown 图片路径替换成 MinIO URL |
| `90` | `saving markdown` | 正在保存最终 `result.md` 到 MinIO |
| `100` | `done` / `failed` | 任务完成或失败 |

## 返回字段

### queued / running

```json
{
  "task_id": "20260625_101010_abcd1234",
  "user_id": "anonymous",
  "filename": "demo.pdf",
  "status": "running",
  "progress": 35,
  "message": "calling MinerU",
  "created_at": "2026-06-25T10:10:10",
  "updated_at": "2026-06-25T10:10:20",
  "error": null
}
```

### done

完成后不会返回 Markdown 原文内容，只返回文件地址和对象路径。

```json
{
  "task_id": "20260625_101010_abcd1234",
  "user_id": "anonymous",
  "filename": "demo.pdf",
  "status": "done",
  "progress": 100,
  "message": "done",
  "error": null,
  "format": "markdown",
  "markdown_url": "http://minio.../result.md?...",
  "markdown_object": "mineru/users/anonymous/tasks/20260625_101010_abcd1234/result/result.md",
  "image_urls": {
    "xxx.jpg": "http://minio.../xxx.jpg?..."
  },
  "image_count": 1,
  "skipped_image_count": 0
}
```

字段说明：

| 字段 | 含义 |
| --- | --- |
| `markdown_url` | MinIO 预签名下载链接，默认有效期由 `MINIO_PRESIGNED_DAYS` 控制 |
| `markdown_object` | MinIO 对象路径，可用于后端重新生成签名链接 |
| `image_urls` | 原图片名到 MinIO 图片 URL 的映射 |
| `image_count` | 实际上传到 MinIO 的图片数量 |
| `skipped_image_count` | MinerU 返回但 Markdown 未引用的图片数量 |

### failed

```json
{
  "task_id": "20260625_101010_abcd1234",
  "status": "failed",
  "progress": 100,
  "message": "failed",
  "error": "MinerU parse failed: 400 ..."
}
```

调用方应展示 `error`，并允许用户重新上传或重试。

## 调用方轮询建议

建议每 2-5 秒查询一次：

```text
GET /parse-md/{task_id}
```

轮询停止条件：

```text
status == done
status == failed
```

不要无限高频请求，避免给后端造成额外压力。

## 注意事项

- 当前任务状态保存在服务内存中；服务重启后，未完成任务状态会丢失。
- 已完成任务的 `result.md` 和图片会保存在 MinIO。
- `markdown_url` 是预签名 URL，默认 7 天有效；过期后需要根据 `markdown_object` 重新生成链接。
- 当前接口不返回 Markdown 原文内容，避免响应体过大。
