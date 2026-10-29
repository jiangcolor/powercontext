# 本地知识库 · StepFun × seekdb

第六届 OceanBase 数据库大赛 StepFun 赛题，团队 owo。浏览器本地执行 embedding，seekdb 保存向量、原文及元数据，并在数据库内执行全文 + 向量混合检索。无需账号、API Key 或付费服务。

## 启动

需要 Node.js 20+、pnpm 10+、Python 3.10+，以及最新版 Chrome / Edge。嵌入式 seekdb 支持 macOS Apple Silicon、Linux x64/arm64、Windows x64；预留至少 1 GB 磁盘空间。

在 `stepfun/local-kb` 目录执行：

```sh
pnpm install --frozen-lockfile
python3 scripts/download-model.py
pnpm start
```

若模型站点不可达：

```sh
python3 scripts/download-model.py --mirror https://hf-mirror.com
```

下载脚本固定模型 revision，并校验 ONNX 文件 SHA-256；已存在且通过校验的模型不会重复下载。模型保存在 `public/models/`，未提交到 Git。首次启动 seekdb 会下载官方原生运行库到 `.data/bindings/`；运行库域名不可达时，可使用官方 S3 的等价入口：

```sh
export SEEKDB_BINDINGS_BASE_URL=https://oceanbase-seekdb-builds.s3-ap-southeast-1.amazonaws.com/js-bindings/all_commits/469a55dc84ea7a9e077161a8b454871a9adaff35
pnpm start
```

Windows PowerShell 使用 `$env:SEEKDB_BINDINGS_BASE_URL="上述地址"` 设置变量。保持本地地址 `http://127.0.0.1:5173`；不要直接从文件系统打开 HTML。模型计算在浏览器 Worker 中完成，模型和 WASM 文件由本地应用提供；浏览器禁用远程模型加载。

## 操作

1. 页面点击“加载量化模型”。支持 FP16 的 WebGPU 优先使用 FP16；没有适合的 GPU 时自动降级到 INT8 WASM。后端选择器可强制 WASM 以验证降级计算流程。
2. 导入 .txt/.md、粘贴文本，或点击“导入示例资料”。长文本按 800 字符分段、重叠 100 字符；片段原文、来源和编号随向量保存。
3. 输入查询，如 `How can I recover a removed file?`。查询也由浏览器生成 384 维向量，后台只把向量和查询文本交给 seekdb。
4. 切换或新建知识库后，检索只访问当前集合；刷新页面会恢复所选知识库。相同来源和内容重复导入使用稳定 ID upsert，连续导入保留已有内容。
5. 点击“运行完整评测”，运行相同语料/查询的 FP32、INT8、批量写入和 WebGPU 对照；完成后可下载 JSON，服务器同时保存在 `evidence/`。

示例语料为自写英文技术与生活文本，标签和查询见 `dataset.js`。all-MiniLM-L6-v2 以英文为主，中文文本可导入且参与 seekdb 全文检索，但本作品不宣称中文语义检索达到同等质量。

## 验证

保持应用运行，在另一个终端执行：

```sh
pnpm test
```

这组真实数据库测试验证增量写入、重复导入、索引刷新后立即可查、集合隔离及无效请求拒绝。测试使用显式标注的合成向量，仅检验数据层；浏览器真实模型推理与质量对比由页面评测完成，原始证据见 `evidence/`。

`TECHNICAL.md` 是一页技术说明；`evidence/RESULTS.md` 记录设备、条件、方法与结果。本地通过和平台正式得分分开记录。

## 数据与结构

- `embed-worker.js`：Transformers.js 本地模型加载、推理后端与降级、向量化进度。
- `app.js`：导入、查询、知识库状态和真实评测。
- `db.mjs`：seekdb-js Schema、显式空 embeddingFunction、索引刷新及数据库 hybridSearch。
- `server.mjs`：本机接口和静态页面；不执行 embedding，不实现检索结果融合。
- `.data/seekdb/`：独立持久化数据库；复验时使用全新目录或新知识库名。

seekdb 集合包含 `id`、`document`、`embedding VECTOR(384)`、`metadata`，配置 cosine HNSW 与 IK 全文索引。每批 upsert 后等待 SDK `refresh_index()`，避免写入完成但索引不可查。`hybridSearch` 的 `query` 与 `knn` 共同提交给 seekdb，`rank.rrf` 在数据库中融合；客户端只展示数据库返回顺序。

如需本机 server 模式，设置 `SEEKDB_HOST`、`SEEKDB_PORT`、`SEEKDB_USER`、`SEEKDB_PASSWORD`、`SEEKDB_DATABASE`；默认嵌入式模式已实际测试。不要把密码、数据库文件、下载模型或依赖缓存提交到仓库。

## 来源与许可

官方题面：https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/hc3pio/kw9wfx4bu9pyvat9 （2026-10-29 核对）。基础提交为官方 `2026-competition-ecosystem` 的 `d647275c308e09b7b623f322a26f5c4e85734fb0`，仅新增 `stepfun/local-kb/`。

模型：https://huggingface.co/Xenova/all-MiniLM-L6-v2 ，revision `751bff37182d3f1213fa05d7196b954e230abad9`，Apache-2.0，源模型 sentence-transformers/all-MiniLM-L6-v2。直接使用模型作者发布的 ONNX 动态 INT8 和 FP16 权重，不训练模型。Transformers.js 3.8.1（Apache-2.0），seekdb-js 1.4.0（Apache-2.0）；其余依赖和完整版本见 package.json 与 pnpm-lock.yaml。

本作品源码和示例资料由 AI 协助实现与调试，并通过真实数据库和浏览器运行验证；没有复用其他队友赛题实现。
