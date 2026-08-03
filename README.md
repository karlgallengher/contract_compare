# Contract Compare Toolset

这个仓库按功能拆成多个独立服务/工具目录，避免 MinerU 解析、文档对比和旧版实验代码混在一起。

## 目录结构

```text
mineru-parser/      MinerU 文档解析接口，负责上传文件、解析 Markdown/JSON、保存 MinIO
document-compare/   文档/合同/表格对比服务，包含 FastAPI 接口和前端页面
home-app/           旧版首页集成应用，包含任务历史和预览相关页面
no-image-md/        无图 Markdown 生成工具
text-extract/       文本提取工具
legacy/             旧版合同对比实验代码
```

## 重要说明

- `.env` 不应提交到仓库，真实密钥和 MinIO 配置请只放在部署环境。
- `.env.example` 只保留变量名示例。
- 各目录可以单独部署，优先看每个目录里的 `README.md`。
- 如果只部署当前主要能力，通常只需要：
  - `mineru-parser/`
  - `document-compare/`

## 常用端口

```text
8010  MinerU Markdown API
8020  Document Compare API
```

## 推荐启动顺序

1. 启动 MinerU 原始解析服务。
2. 启动 LibreOffice 转换服务。
3. 启动 `mineru-parser` 的 `8010` 服务。
4. 启动 `document-compare` 的 `8020` 服务。

## 安全

上传到 GitHub 前已移除明显的 API key/JWT token。后续不要把 `.env`、真实密钥、MinIO secret、模型 key 提交到仓库。
