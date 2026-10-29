# 一页技术说明：本地知识库

**任务与实现。** 团队 owo；资产位于 stepfun/local-kb。浏览器 Worker 使用 Transformers.js 3.8.1 编码文档和查询，mean pooling + L2 归一化得到 384 维向量。Node 后台仅通过 seekdb-js 1.4.0 保存资料和发起检索，不执行 embedding；禁用远程模型加载，WASM 与模型由本机提供。

**模型与量化。** Apache-2.0 的 Xenova/all-MiniLM-L6-v2，固定 revision 751bff37182d3f1213fa05d7196b954e230abad9。使用作者发布的 ONNX 动态 INT8（model_quantized.onnx）及 FP16（model_fp16.onnx），下载后校验 SHA-256。含相同 tokenizer/config 的模型包为 FP32 91.33 MB、INT8 23.92 MB、FP16 46.24 MB，压缩比分别 3.8188、1.9751。16 篇固定英文语料、16 条标注查询，重复三次，FP32、INT8 WASM、FP16 WebGPU Recall@3 均 0.9375；nDCG@3 分别 0.8683、0.9144、0.8683。

**端侧运行。** 自动检测 WebGPU 适配器及 shader-f16，显式选择 WebGPU FP16；不可用或初始化失败时自动用 INT8 WASM，页面显示实际后端。已实测真实 WebGPU 与强制 WASM 的完整流程，未另测无 GPU 设备。模型首次本地加载与预热后推理分开记录，pipeline 复用；公网下载耗时未冒充推理性能。

**seekdb 与状态。** 独立嵌入式实例持久化 ID、原文、384 维向量和来源/分段元数据；cosine HNSW + IK 全文索引。embeddingFunction 显式为 null，确保后台不自动向量化。hybridSearch 同时提交全文 query、向量 knn 及 rank.rrf，融合在 seekdb 中执行。稳定内容 ID upsert，批写后等待 refresh_index；切换集合只查当前知识库，浏览器保存所选集合名。支持连续导入、去重和刷新后立即检索。

**实测优化。** Apple M5 / 32 GB / macOS 26.6 / Edge 156，16 篇资料、每配置三次导入与 48 次查询。保持 INT8 WASM 和 batch=1，写入由逐条改为整批，完整导入中位数从 6617.1 ms 降至 526.5 ms，约 12.57 倍，Recall/nDCG 不变。FP16 WebGPU 向量化为 82.8 ms，seekdb 检索 3.47 ms，端到端查询 11.7 ms；INT8 WASM 端到端 12.2 ms。未采用未见收益的 batch=8，也未采用质量下降的 INT8 WebGPU。

**复现。** pnpm install --frozen-lockfile；python3 scripts/download-model.py；pnpm start。打开 http://127.0.0.1:5173，导入资料并检索，点击完整评测。依赖锁、数据集、原始测量、模型大小与哈希、真实数据库回归均随源码提供。详见 README.md 和 evidence/RESULTS.md；正式成绩以平台为准。
