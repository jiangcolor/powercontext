# 规有所依：工单筛选开发上下文模块

MiniMax × OceanBase 赛题作品。演示给工单列表增加状态筛选，并保持排序、limit 和不修改输入的兼容行为。只提供一个 CLI，不引入完整 Agent 框架。

**真实 MiniMax-M2.7 已参与代码修改；验收结果与运行日志见 evidence/。正式比赛成绩以平台判题为准。**

## 环境与安装

Python 3.12；Linux x86_64 或 macOS arm64。PowerContext 1.2.0、pylibseekdb 1.4.0.post1、PyMySQL 1.2.3；完整依赖见 requirements.lock。内嵌 seekdb 启动需要正常的本地进程、套接字和非 loopback 网络地址；Linux 容器可参考 PowerContext 官方自测容器的虚拟网卡配置。

在本目录运行：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
```

模块不依赖本机其他作品。seekdb 的资料和 PowerContext 的状态均在本目录 `.state/` 创建。PowerContext 使用 SQLite 持久化状态；工程资料由真实 seekdb 存储和全文检索，二者承担不同职责。

## 调用入口

`python -m sdd_context 命令`，支持 `--task`、`--project`、`--state` 和 `--evidence`。默认业务工程为 `demo/`；默认输出记录为 `evidence/`。输出是 UTF-8 JSON。

- `ingest`：将当前规格、初始代码及同一组测试导入 seekdb。按路径和 SHA-256 定位，每次完整导入替换旧快照，删除的文件不继续参与检索。
- `context`：按任务执行真实 seekdb FTS，返回来源路径、全文、行号范围与摘要哈希，并读取 PowerContext 中已有任务状态。缺少规格、代码或测试任一类时拒绝生成开发上下文。
- `record --done ... --todo ... --validation ...`：把任务进展写入 PowerContext Memory。
- `resume`：启动新的独立 PowerContext 进程，查询已保存状态并返回引用。空数据库返回空状态。
- `develop`：把数据库检索与状态复用得到的上下文交给 MiniMax，保存实际开发记录与代码差异，生成 `demo/after/tickets.py`。
- `verify --phase before|after`：运行完全相同的目标与回归测试，保存命令、退出码、代码和测试的 SHA-256。before 阶段预期目标行为失败，回归通过；after 阶段两组必须全部通过。

## 验证样例

任务与规格见 `demo/specs/tickets.md`。

必要来源：

1. `demo/specs/tickets.md` 的 SPEC-STATUS 和 SPEC-COMPAT。
2. `demo/before/tickets.py` 的 `list_tickets`。
3. `demo/tests/test_tickets.py` 的 `TargetStatusTests` 与 `RegressionTests`。

初始数据是测试中的 RECORDS：四个工单，覆盖 open、in_progress 和 closed。目标行为：按状态精确筛选、先筛选再限制、无匹配返回空列表、不支持的状态报错。原有排序、默认 limit=10、limit=0、非法 limit 与输入保持不变都必须继续通过。

```sh
.venv/bin/python -m sdd_context verify --phase before
.venv/bin/python -m sdd_context ingest
.venv/bin/python -m sdd_context context
.venv/bin/python -m sdd_context record --done '基线目标失败、回归通过' --todo 'MiniMax 修改状态筛选' --validation 'before checked'
.venv/bin/python -m sdd_context resume
.venv/bin/python -m sdd_context context
```

## MiniMax 安全配置和实际开发

使用 MiniMax 官方 M Plan 订阅 Key。通过本机环境变量 `MINIMAX_API_KEY` 提供，或放入本目录 `.secrets/minimax-key`（文件权限 0600）。不要提交到仓库。默认模型 MiniMax-M2.7；可通过 `MINIMAX_MODEL` 调整。默认中国区 OpenAI 兼容端点；国际区可设置 `MINIMAX_ENDPOINT=https://api.minimax.io/v1/chat/completions`。只有两个官方端点被允许。

```sh
.venv/bin/python -m sdd_context develop
.venv/bin/python -m sdd_context verify --phase after
.venv/bin/python -m sdd_context record --done 'MiniMax 代码修改与目标、回归测试通过' --todo '无' --validation 'after checked'
.venv/bin/python -m sdd_context resume
```

`evidence/minimax-request.json` 保存实际任务上下文，不含鉴权头；`minimax-development.json` 保存模型、响应 ID、usage 和最终代码文本，不保存私有推理过程；`code.patch` 对应修改前后快照。只有真实请求成功才生成开发记录，不存在模拟替代路径。

## 从干净环境复验

```sh
.venv/bin/python check_context.py
.venv/bin/python replay.py
```

前者不调用 MiniMax，真实验证资料入库与检索、规格更新重新导入后替换旧内容、从空状态写入并跨进程复用，以及基线目标失败与回归通过。后者要求已交付真实 MiniMax 开发记录和 after 快照，使用独立临时数据库复验整个结果，无需模型再次生成相同补丁。

重置方法：使用新的 `--state /新的空目录` 和 `--evidence /新的日志目录`，保留源码和已交付原始证据；不要复用其他比赛作品的数据。`check_context.py` 和 `replay.py` 自动使用临时空状态。

## 限制与来源

演示仅处理单个小型 Python 工程的文本资料。状态保留在 PowerContext，未恢复完整 Agent 会话。真实模型调用、修改前后同一组测试和状态恢复验证均保留原始记录；本地验证不等于正式判题成绩。

业务样例和上下文模块为本作品编写。PowerContext：https://github.com/oceanbase/powercontext，Apache-2.0；seekdb：https://github.com/oceanbase/seekdb，按其发布包许可使用。未复制或修改其他队友题目代码。
