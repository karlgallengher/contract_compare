# Home App

旧版首页集成应用。

## 功能

- 文件上传解析
- 历史任务展示
- Markdown/JSON/PDF 预览
- 与 MinIO 存储集成

## 启动

```bash
uvicorn app_home:app --host 0.0.0.0 --port 8000
```

启动后打开：

```text
http://127.0.0.1:8000/
```

## 说明

这个目录保留旧版集成页面。当前主要部署推荐使用：

```text
mineru-parser/
document-compare/
```
