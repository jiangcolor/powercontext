# 时间回收站 · Time Lost & Found

把一件离谱物品交给失物招领员“零点”，选择让它自由、打工或成为朋友，下次来访时看看发生了什么。三次独立 Dify 运行组成一个完整故事，玩家只需保管同一张玩家卡。

**已完成真实 Dify Cloud 三幕测试，并在新应用重新导入后复验通过。** 玩家选择通过真实 PowerContext 保存和召回；不是本地模拟。比赛使用的基础分支为 `oceanbase/powercontext:2026-competition-ecosystem`，所有作品文件在 `dify/time-lost-found/`。

## 技术与版本

- Dify Cloud：2026-10-28 实测，DSL 格式 **0.7.0**。云端未展示具体构建版本，不宣称兼容未经测试的自建旧版本。
- 叙事模型：`qwen-plus`，供应商 `langgenius/tongyi/tongyi`，Marketplace 插件 **langgenius/tongyi 0.2.26**。DSL 已记录插件版本与唯一标识。使用工作区试用额度完成了测试；评审需配置自己的可用模型额度。
- PowerContext **1.4.1**：显式 Memory 写入及 SQLite 全文召回，不需要为 PowerContext 配置推理模型、Embedding 或 Rerank。
- 配套后端：Python **3.12.14**、FastAPI **0.162.0**、Uvicorn **0.54.0**，实测平台 macOS ARM64。
- 无自定义 Dify 插件，无外部素材、预置知识库或数据集。

Dify 编排表单、HTTP 工具、回执检查、模型叙事和输出。PowerContext 保存并复用物品与选择；召回内容实际进入模型输入。后端 SQLite 只保存精确游戏状态、Scope 绑定和请求回执，不替代 PowerContext。

## 运行：只需两个服务和一个 DSL

在本目录打开终端，安装 Python 3.12 后执行：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

`requirements.lock.txt` 是本次 macOS ARM64 的完整依赖快照；相同平台可用它精确安装，其他平台从直接依赖安装并复验。

终端一，启动记忆服务：

```bash
source .venv/bin/activate
export POWERCONTEXT_HOME="$PWD/var/powercontext"
powercontext server run --host 127.0.0.1 --port 8900 --no-env-file
```

终端二，启动作品服务：

```bash
source .venv/bin/activate
export POWERCONTEXT_URL=http://127.0.0.1:8900
export GAME_DATA_DIR="$PWD/var/game"
uvicorn server:app --host 127.0.0.1 --port 8787 --workers 1
```

PowerContext 此版本使用 SQLite 时不要加 `--role api`。未配置推理模型的启动提示不影响本作品使用的显式 Memory 与全文检索。

### 导入 Dify

1. 在 Dify 工作室选择“导入应用”，导入 **`time-lost-found.yml`**，只有这一个必需 DSL，无先后顺序。
2. 确认工作区安装通义插件 0.2.26，并能使用 `qwen-plus`；需要时在“零点讲述这次来访”节点重新选择已配置的 Chat 模型。模型密钥只在 Dify 供应商设置中配置，不写进源码或 DSL。
3. 配置环境变量 `BRIDGE_URL` 为 **Dify 服务端实际可访问的作品服务地址**；有认证时把 `BRIDGE_TOKEN` 设置为 Secret 类型，与作品服务一致。
4. 点击“测试运行”，按下表依次执行三次，每次使用同一张玩家卡。

| 次序 | 动作 | 输入 | 预期 |
|---|---|---|---|
| 1 | 寄存 | 一只只在周一响的闹钟 | 第 1 幕、三个去向、记忆 empty 并完成写入 |
| 2 | 改写 | 朋友。我想让它有个愿意等它的人。 | 第 2 幕、认出闹钟、记忆 ready、提示立即重逢 |
| 3 | 重逢 | 留空 | 呼应朋友选择、为玩家留椅子、结局“异物知己”、故事完成 |

玩家卡使用新的至少 12 位字母数字组合。同一张卡关联同一 Scope；换卡即全新故事，不需要删除数据库。实际叙事文字不固定，但物品、章节、分支和结局必须正确。其他分支及异常样例见 `docs/acceptance.md`。

### 网络与认证

- Dify 与作品服务在同一台宿主进程运行时，可使用 `http://127.0.0.1:8787`。
- Dify 在 Docker Desktop 内时，通常使用 `http://host.docker.internal:8787`，但必须验证容器到宿主的监听地址与访问策略。默认回环监听不保证所有容器环境都能访问。
- Dify Cloud 无法访问你电脑的 `127.0.0.1`。需使用自己的可达 HTTPS 服务，或开启经过授权的临时连接；**本次 Cloudflare 临时连接已在测试结束后关闭，提交文件不依赖它**。完整启动方法与认证配置见 `.env.example`，该文件仅作示例，不自动加载。
- 跨机器时设置随机 `BRIDGE_TOKEN`，或只在服务端配置其 SHA256 摘要 `BRIDGE_TOKEN_SHA256`；Dify 仍发送原始 Bearer 凭据。启用 `PUBLIC_BRIDGE=1` 会关闭开发文档与 OpenAPI 端点。PowerContext 保持仅由作品服务访问。
- 本作品的评审方式是导入 DSL、启动服务并执行验证样例；不要求评审依赖作者电脑保持在线。作者工作区已保存的入口：[Dify 应用](https://cloud.dify.ai/app/3a0c4883-08da-4441-b6fc-2120cc0969a3/workflow)，需要作者工作区权限，并需按实际运行环境重绑服务地址。

## 证据和复验

- `evidence/live-dify.json`：真实 Dify UI 观察转录，包含最终重导入应用的三幕输出和回执；明确区分早期发现的问题与最终复验。
- `evidence/live-dify-callbacks.json`：真实、已认证的 Dify HTTP 调用产生的 PowerContext 响应，包含历史内容和 Artifact 引用。
- `evidence/live-backend.json`：三种结局、玩家隔离、重试与输入校验，共 17 次真实后端请求。
- `evidence/resilience.json`、`evidence/resilience-hash-auth.json`：认证拒绝、真实上游连接失败、进程重启后恢复。
- `docs/demo.md`：可直接照读的演示脚本；官方未强制录屏，本次以实际输出和运行记录交付，不额外制作视频。

可运行检查：

```bash
python tests/check_dsl.py
python tests/verify_live.py
python tests/verify_resilience.py
```

前者是静态检查，不代替 Dify 实测。`tests/verify_dify.py` 提供可选的真实 Dify API 验证方法，需自行通过安全的运行配置注入 `DIFY_APP_API_KEY`；本次实测使用 UI，没有使用该 API 脚本伪造记录。

## 限制与恢复

- 单实例、单 worker 演示；不提供账户系统。玩家卡是故事访问凭据，只保存虚构物品和选择。
- 主玩法为三幕，历史召回预算 12 KB，不承诺无限长剧情。叙事有随机性，规则与结局由程序固定。
- 选择先存档、后调用叙事模型。模型失败时选择仍然生效，可按当前章节继续下一步或重跑失败叙事节点。
- 普通 HTTP 重试返回同一回执；若恰在 PowerContext 写入后、本地事务提交前崩溃，可能多存一条相同记忆，两套存储没有分布式事务。
- 停止服务按 Ctrl+C；完全重置时停止服务后将本作品 `var/` 整体改名备份，再启动。不要只移动一份数据库。

## 来源

玩法、规则、数据与配套代码为原创。官方运行接口：[PowerContext API 快速开始](https://powercontext.oceanbase.io/zh/docs/develop/api-quickstart/)。最初图结构参考 [Dify 官方基础测试样例](https://github.com/langgenius/dify/blob/1.9.1/api/tests/fixtures/workflow/basic_chatflow.yml)，最终根据真实 Cloud 导出结构与插件绑定调整到 DSL 0.7.0，并重新导入实测。

官方题面与分支要求见 `docs/requirements.md`；提交材料清单见 `docs/submission.md`。
