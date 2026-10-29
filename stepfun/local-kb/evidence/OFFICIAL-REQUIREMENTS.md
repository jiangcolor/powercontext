# 官方要求核对

核对时间：2026-10-29（Asia/Shanghai）。

- 官方平台题目：StepFun / 端侧 AI 推理性能优化与 seekdb 混合检索，questionId 600073，subQuestionId 800510，总分 20。
- 完整题面：https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/hc3pio/kw9wfx4bu9pyvat9 ，页面更新标记 10-26 11:53。
- 开发基础：https://github.com/oceanbase/powercontext/tree/2026-competition-ecosystem ，核对 SHA d647275c308e09b7b623f322a26f5c4e85734fb0；资产放 stepfun 目录。团队仓库默认分支 batch1，生态开发分支 eco，与官方轻量基础分支不同。本作品直接基于官方明确指定的基础提交创建独立分支，保留团队原分支。
- 模型可自选公开开源 embedding；不限定 StepFun 模型，无需阶跃账号。必须在浏览器本地计算文档和查询向量；禁止云端推理、服务端预计算回放和其他数据库替代。
- INT8 或 FP16；记录量化前后体积、压缩比与固定评测集质量；优先 WebGPU，不支持时自动 WASM，显示实际后端。
- 使用 seekdb-js；向量、原文、ID 与元数据存 seekdb，全文与向量融合由数据库执行。增量导入、索引刷新和集合/会话切换正确。
- 提供可运行应用、完整源码、依赖/配置/模型获取、数据库结构和索引、复现数据与一页技术说明。对比实验保留原始重复测量，区分首次加载、预热与查询延迟。
- 页面未公布逐项分数权重；不自行编造分项得分。正式结果以平台记录为准。
