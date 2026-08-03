# Document Compare

文档、合同和表格对比服务，包含后端接口和前端页面。

## 功能

- 上传两个文件进行对比
- 支持合同模式、普通文档模式、表格模式
- 返回差异列表和高亮后的页面图片
- 调用 `mineru-parser` 获取 Markdown/Layout JSON
- 当前版本已改为任务式异步接口

## 启动

```bash
uvicorn contract_compare_api:app --host 0.0.0.0 --port 8020
```

启动后打开：

```text
http://127.0.0.1:8020/
```

## 接口

```text
POST /compare
POST /compare-contract
GET  /compare/{task_id}
GET  /health
```

`POST /compare` 会立即返回：

```json
{
  "task_id": "...",
  "status": "queued",
  "progress": 0
}
```

完成后通过 `GET /compare/{task_id}` 获取：

```json
{
  "status": "done",
  "compare_mode": "contract",
  "diffs": [],
  "before_images": [],
  "after_images": []
}
```

## 对比模式

```text
contract  合同模式，包含签署区/附件等合同规则
document  普通文档模式，减少合同专用规则
table     表格模式，直接比较表格单元格/行差异
```

## 支持上传类型

```text
pdf
doc
docx
xls
xlsx
csv
```

## 关键环境变量

```env
MINERU_MD_API_URL=http://127.0.0.1:8010
DOCUMENT_CONVERT_URL=http://10.89.31.94:8009/convert
COMPARE_PARSE_TIMEOUT=600
COMPARE_POLL_INTERVAL=2
DEEPSEEK_API_KEY=
```

## 部署依赖

- `mineru-parser` 服务必须可访问
- LibreOffice 转换服务必须可访问
- 如果启用签署区字段判断，需要配置 `DEEPSEEK_API_KEY`
