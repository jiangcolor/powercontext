# 提交材料

题目：Just for Fun——用 Dify 做一个好玩的智能应用，20 分。

题号：questionId `600076`，subQuestionId `800513`；2026-10-28 在实际平台页面已核对题名、分值与要求。细分评分权重仍以官方后续规则为准。

团队：owo。用户已确认使用 `jiangcolor/powercontext` 的独立 Dify 分支。

## 代码位置

- 仓库：`https://github.com/jiangcolor/powercontext`
- 分支：`competition/dify-time-lost-found`
- 基础 commit：`d647275c308e09b7b623f322a26f5c4e85734fb0`，来自官方 `2026-competition-ecosystem`。
- 作品目录：`dify/time-lost-found/`。
- 最终提交 commit 以交付时的“提交信息”记录为准，不使用早期本地开发 commit。

## 材料核对

- [x] 一个可导入 DSL：`time-lost-found.yml`，格式 0.7.0，通义 0.2.26 / qwen-plus 绑定。
- [x] 完整后端源码、依赖、占位配置与启动步骤。
- [x] 无预置数据依赖，首次寄存自动建立 Scope。
- [x] 一组完整真实 Dify 样例：寄存 → 朋友 → 重逢。
- [x] PowerContext 实际记忆写入及后续召回记录。
- [x] 在干净应用重新导入 DSL，完整重跑三幕。
- [x] 修复额外玩法提示和重复回执，并以最终复验记录交付。
- [x] 演示脚本与实际输出记录；不额外制作非必需视频。
- [x] 试验结束关闭临时公网连接，提交不依赖作者电脑在线。
- [x] 源码和 DSL 不含真实 API Key、认证凭据或平台私密仓库 URL。

## 平台填写说明

在 Dify 对应赛题填写 PowerContext 团队仓库及本作品分支/最终 commit，材料路径为 `dify/time-lost-found/`。不要填 seekdb 分支或暂停的赛题十 commit。

如果平台现有仓库配置涉及账号或认证 URL，由用户在平台自身的安全界面确认；不要把含凭据地址复制到聊天、源码、截图或 README。GitHub 仓库名称与可写权限已经确认，但平台最终提交及判分结果应单独核对，不能以源码上传代替提测成功。

## 提交说明正文

作品「时间回收站」使用 Dify 编排三幕互动：寄存一件离谱物品，选择自由、打工或朋友，再在新的独立运行中重逢。PowerContext 1.4.1 保存并召回玩家物品和选择，记忆实际进入 Dify 模型输入，影响第三幕结局。已在 Dify Cloud 重新导入后执行完整样例，提供真实故事输出、回执、Memory Artifact 引用以及可复现运行说明。无自定义插件、预置知识库或额外媒体服务依赖。
