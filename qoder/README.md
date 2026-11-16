# 论文脉络图 — 基于 PowerContext 的文献综述智能助手

个人文献管理工具，基于 **PowerContext** 框架构建，自动提取论文信息、构建引用关系图、发现语义关联，辅助 Related Work 写作。

## ✨ 核心特性

### 基于 PowerContext 框架
- **Artifact 系统**：论文建模为 PowerContext Artifact，支持版本追踪和血缘管理
- **SQLite 持久化**：使用 PowerContext 的 SQLite Profile，支持 FTS5 全文搜索和 sqlite-vec 向量索引
- **混合检索**：结合 BM25 全文搜索和向量语义搜索，使用 RRF（Reciprocal Rank Fusion）融合排序
- **Topic Memory**：结构化主题聚类，支持渐进式披露和相关性分析

### 功能特性
- **批量上传**：支持一次选择多个 PDF，自动解析并去重
- **PDF 智能解析**：自动提取标题、摘要、方法、结论、参考文献
- **自动去重**：基于标题相似度检测重复论文，避免重复入库
- **语义检索**：基于 TF-IDF 或 OpenAI Embedding 的论文语义搜索
- **脉络图可视化**：引用关系、语义相似、同一作者三种关系类型的交互式图谱（ECharts）
- **研究画像**：记录研究方向和阅读进度，新论文自动关联已有文献
- **写作助手**：按主题聚类生成 Related Work 大纲，每篇论文一句话贡献总结

## 🚀 快速部署

### 1. 环境准备

确保已安装：
- Python 3.11+（推荐 64 位）
- pip

验证安装：
```powershell
python --version  # 应该显示 3.11 或更高
pip --version
```

### 2. 进入项目目录

```powershell
git clone --branch competition/qoder-paper-graph https://github.com/jiangcolor/powercontext.git
cd powercontext/qoder
```

### 3. 创建虚拟环境（推荐）

```powershell
python -m venv venv
venv\Scripts\Activate.ps1 # Windows PowerShell
# macOS / Linux: source venv/bin/activate
```

### 4. 安装依赖

首先安装 PowerContext：

```powershell
python -m pip install -e "..[builtin]"
```

然后安装其他依赖：

```powershell
pip install -r requirements.txt
```

> 如果网络有问题，使用国内镜像：
> ```powershell
> pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn
> ```

### 5. 配置 API Key

```powershell
copy .env.example .env
```

编辑 `.env` 文件，填入你的 LLM API Key：

```ini
# 支持 OpenAI / DeepSeek / 其他 OpenAI 兼容接口
OPENAI_API_KEY=sk-your-actual-key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini

# 可选：使用专门的嵌入模型（留空则用内置 TF-IDF 向量化）
EMBEDDING_MODEL=
```

**国内用户推荐**：可使用 DeepSeek API：
```ini
OPENAI_API_KEY=sk-your-deepseek-key
OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_MODEL=deepseek-chat
```

> **无 API Key 也能使用**：系统会跳过 LLM 提取步骤，使用 PDF 原始解析结果。向量检索会使用内置的 TF-IDF 向量化（无需额外模型）。

### 6. 数据迁移（可选）

如果从旧版本升级，运行迁移脚本：

```powershell
python migrate_to_powercontext.py
```

这会将旧数据库（`data/papers.db`）中的论文迁移到 PowerContext 格式（`data/papers_powercontext.db`）。

### 7. 启动应用

```powershell
python app.py
```

浏览器打开 `http://localhost:5000`。

### 验证主要功能

安装依赖后，在本目录运行 `python smoke.py`。脚本用临时数据目录和合成 PDF 验证上传预览、确认保存、文献检索、图谱、写作提纲、并发读取及重启后的数据持久化。整个过程无需 API Key。

## 比赛现场演示（无需 API Key）

下面的流程与 `smoke.py` 的六个环节一一对应：**上传预览 → 确认保存 → 语义检索 → 脉络图 → 写作大纲 → 重启后数据仍在**，全程不请求 LLM 或 Embedding 接口。

### 为什么不需要 Key

`config.py` 通过 python-dotenv 读取 `.env`，`OPENAI_API_KEY` 缺省为空；`app.py` 的判断是「Key 为空或以 `sk-your` 开头就跳过 LLM」。

| 环节 | 有 Key | 无 Key（演示路径） |
|------|--------|--------------------|
| 结构化抽取 | 模型输出标题/作者/年份/方法/贡献/主题 | 只用 PyMuPDF 文本层结果，其余字段由讲解人手填 |
| 一句话贡献 | 模型生成 | 直接用表单里手填的「贡献总结」 |
| 向量与聚类 | 可选 OpenAI Embedding | 本地共享词汇表 TF-IDF + 余弦相似度（`vector_store.py`） |
| 语义相似边 | 保存时调用模型判断 | 跳过，不写 `semantic_similar` 关系 |
| 写作大纲 | 模型生成 Related Work | 模板化的主题概览 / 分主题清单 |

演示机上不放 `.env` 即可；若目录里已有带真实 Key 的 `.env`，请在 shell 里显式导出空 Key——`load_dotenv()` 默认不覆盖已存在的环境变量。

### 赛前一次性准备（需联网）

1. 按上面「快速部署」第 1–4 步装好 PowerContext 与 `requirements.txt`。
2. 准备 **2–3 份有文本层的论文 PDF**（arXiv 直接下载的版本即可，不要用扫描件）：解析走 `page.get_text()`，扫描件抽不到文字，标题会退化成文件名、摘要为空。
3. 用浏览器访问一次 `https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js`，确认这台机器能取到它：`/graph` 页面的 ECharts 由该 CDN 加载（`app.py` 的 `BASE_TEMPLATE`），这是整个演示流程唯一的前端外网依赖。
4. 冒烟验证：`python smoke.py`。脚本用 Flask test client 在临时数据目录里跑完同样六个环节，不启动浏览器，因此不会请求该 CDN。

### 现场步骤

**1. 干净启动**

```powershell
$env:DATA_DIR = "$PWD\data-demo"   # 空目录，避免旧数据干扰
$env:OPENAI_API_KEY = ""
python app.py
```

```bash
export DATA_DIR="$PWD/data-demo"
export OPENAI_API_KEY=""
python app.py
```

打开 `http://localhost:5000`。`DATA_DIR` 下的 `uploads/`、`papers_powercontext.db`、`papers.db`、`vectors.db` 会在导入配置和启动时自动创建。侧边栏的「研究画像」可跳过：当前 `SyncPaperStore.get_profile/save_profile` 是未持久化的桩，演示不依赖它。

**2. 上传并确认（`/upload`）**
- 「选择文件」挑一份 PDF →「批量上传并解析」。文件名必须以 `.pdf` 结尾，否则该文件被忽略。
- 预览页自动带出的只有文本层结果：**标题**取正文前 10 行里第一条长度 15–300 字符、且不以 `Abstract`/`Keywords`/`Introduction`/数字/`arXiv`/`doi`/URL 开头的行；**摘要**取 `Abstract` 之后的一段。
- 现场补 **作者、年份、会议/期刊、核心方法**，尤其要填 **主题分类**（3–5 个英文词）：脉络图的分组配色和写作大纲的主题分组都读这个字段。
- 「✅ 批量保存」一次写入三处：Paper Artifact → `papers_powercontext.db`；PDF 原件 → `data-demo/uploads/<artifact_id>.pdf`；TF-IDF 向量（索引文本 = 标题 + 摘要 + 方法）→ `vectors.db`。
- 换第二、第三份重复一次。再传同一份 PDF 会命中**标题去重**（完全相同或互为子串），预览页下方出现「检测到重复论文」卡片（界面固定显示相似度 90%），适合作为讲解点。

**3. 语义检索（`/search`）**

输入**与标题、摘要同语言的英文关键词**（如 `vector retrieval`），回车即得带相似度的结果卡片。两个讲解注意点：无 Key 时索引文本基本只含标题+摘要（「核心方法」多为空或手填），命中词请从中挑；TF-IDF 按空白切词，中文查询与英文正文不共享 token。

**4. 脉络图（`/graph`）**

节点是论文，标签为「年份 + 标题前 25 字」，颜色按主题分类分组，支持拖拽与缩放。如实说明：**离线保存流程只产出节点，不产出连线**——引用边要求保存请求携带非空 `references_json`（预览页该隐藏字段固定为 `[]`），语义相似边只在有 Key 的分支里调用 `discover_semantic_links`，同作者边当前没有路由触发。所以现场看到的是带主题配色的论文节点云；若一定要演示一条边，可用浏览器开发者工具把某篇的 `references_json_0` 改成库内另一篇标题的 JSON 数组（两条标题需互为子串）再提交。

若 CDN 取不到：`/graph` 仍返回 200，节点与连边以 JSON 内嵌在页面的 `var data = ...` 中，可改用「📊 总览」+「📚 文献库」继续讲；也可赛前把 `echarts.min.js` 放到本机并把 `BASE_TEMPLATE` 的 `script src` 指到本地路径（需自行改 `app.py`，本 README 的部署步骤不含该改动）。

**5. 写作大纲（`/writing`）**

选「全部主题概览」→「🚀 生成大纲」，输出按主题分组的论文清单（每主题最多 5 篇，附年份与贡献，缺贡献时取摘要前 100 字）；选具体主题则逐篇列出标题、前 3 位作者、贡献，无 Key 时用摘要前 200 字符代替。

**6. 收尾：持久化与聚类**
- `Ctrl+C` 停服，保留同一 `DATA_DIR` 再次 `python app.py`，`/library` 仍列出全部论文——这正是 `smoke.py` 最后重启断言的行为。
- 时间允许再演示「📚 文献库 → 🔄 重新聚类」（阈值 0.3 粗 / 0.7 细）：纯本地 TF-IDF + 并查集，无需 Key；注意它会按相似度**重写**主题标签，且少于 2 篇论文时统一落到「未分类」，建议作为最后一步。

### 兜底

- 端口冲突：`python -m flask --app app run --port 5001`（macOS 上 5000 常被 AirPlay 占用）。
- 提示「无法读取 PDF，请检查文件后重试」：文件不是可被 PyMuPDF 打开的 PDF。
- 除第 4 步的图表渲染依赖 CDN 外，其余步骤在完全断网的机器上都能跑通。

## 📁 项目结构

```
qoder/
├── app.py                      # Flask 主应用（含 HTML 模板）
├── config.py                   # 配置管理
├── paper_artifacts.py          # Paper Artifact 模型定义（基于 PowerContext）
├── paper_store.py              # Paper 持久化层（使用 PowerContext SQLite Profile）
├── sync_paper_store.py         # 同步包装器（用于 Flask 路由）
├── migrate_to_powercontext.py  # 数据迁移脚本
├── pdf_parser.py               # PDF 解析（PyMuPDF）
├── vector_store.py             # 向量存储（TF-IDF / OpenAI Embedding）
├── llm_utils.py                # LLM 调用封装（OpenAI 兼容接口）
├── graph_builder.py            # 关系图构建
├── database.py                 # 旧版数据库层（保留用于关系存储）
├── requirements.txt            # Python 依赖
├── .env.example                # 环境变量模板
├── README.md                   # 本文件
└── data/                       # 运行时数据（自动创建）
    ├── papers_powercontext.db  # PowerContext SQLite 数据库（论文 Artifact）
    ├── papers.db               # 旧版数据库（论文关系）
    ├── vectors.db              # 向量索引
    └── uploads/                # PDF 文件存储
```

## 🔧 技术架构

### PowerContext 集成

本工具深度集成 PowerContext 框架：

| 组件 | PowerContext 模块 | 用途 |
|------|------------------|------|
| **Artifact 系统** | `powercontext.artifacts` | 论文建模为不可变 Artifact，支持版本追踪 |
| **SQLite 持久化** | `powercontext.builtin.persistence.sqlite` | 异步数据库连接、事务管理、WAL 日志 |
| **全文搜索** | SQLite FTS5 | 论文标题、摘要、方法的全文检索 |
| **向量搜索** | sqlite-vec | 语义向量索引和相似度检索 |
| **混合检索** | RRF 融合 | 结合 BM25 和向量搜索的排序 |

### 数据模型

**Paper Artifact**：
```python
class PaperContent(BaseModel):
    title: str
    authors: list[str]
    year: int | None
    venue: str | None
    abstract: str | None
    methods: str | None
    contributions: str | None
    conclusions: str | None
    references: list[str]
    topic_cluster: str | None
    pdf_path: str | None
    tags: list[str]
    is_relevant: bool
    created_at: datetime

class Paper(Artifact[PaperContent]):
    family: Literal["paper"] = "paper"
```

### 其他技术栈

| 组件 | 技术 |
|------|------|
| Web 框架 | Flask 3.x（支持 async 路由） |
| PDF 解析 | PyMuPDF (fitz) |
| 图可视化 | ECharts（CDN 加载） |
| LLM | OpenAI API（兼容 DeepSeek / Ollama 等） |

## 📖 使用指南

### 第一步：设置研究画像

进入「研究画像」页面，填写：
- **研究方向**：你的主要研究领域（如：Graph Neural Networks, Knowledge Graphs）
- **关注关键词**：具体技术关键词（如：attention mechanism, GNN, link prediction）

**研究画像的作用**：
- 上传论文时，自动标记与你的研究相关的论文
- 文献库中，可筛选出与你研究方向相关的论文
- 写作助手中，优先生成与你研究方向相关的大纲

### 第二步：上传论文

进入「📤 上传论文」页面：
1. 点击「选择文件」，可一次选择多个 PDF（批量上传）
2. 系统自动解析并提取每篇论文的结构化信息
3. **自动去重**：系统会检测与已有论文的标题相似度，标记可能的重复
4. 确认/修改每篇论文的提取结果
5. 点击「批量保存」

系统会自动：
- 将论文作为 Artifact 存入 PowerContext 数据库
- 构建 FTS5 全文索引和向量索引
- 解析参考文献列表，建立引用关系
- 与已有论文进行语义匹配，发现隐性关联
- 跳过已标记为重复的论文（可手动覆盖）

### 第三步：自动聚类

进入「📚 文献库」页面：
- 点击「🔄 重新聚类」按钮，系统会基于论文向量相似度自动聚类
- 调整相似度阈值（0.3=粗聚类，0.7=细聚类，默认 0.5）
- 聚类完成后，可按主题筛选查看

**聚类原理**：使用共享词汇表的 TF-IDF 向量化所有论文，计算余弦相似度，相似度超过阈值的论文归为同一主题。

### 第四步：浏览脉络图

进入「🕸️ 脉络图」页面：
- 🔴 红色边 = 引用关系
- 🔵 蓝色边 = 语义相似（方法相关但互不引用）
- 🟠 橙色边 = 同一作者

可按主题聚类筛选查看。支持拖拽节点和缩放。

### 第五步：语义检索

进入「🔍 语义检索」页面，输入自然语言查询，如：
- "图神经网络在知识图谱补全中的应用"
- "attention mechanism for graph learning"

系统使用 PowerContext 的混合检索（FTS + 向量 + RRF 融合）返回最相关的论文。

### 第六步：生成写作大纲

进入「📝 写作助手」页面：
- 选择主题聚类
- 点击「生成大纲」
- 系统自动按主题分组，生成 Related Work 章节结构

## 🔑 设计决策

### 为什么使用 PowerContext？

1. **Artifact 系统**：论文作为不可变 Artifact，支持版本追踪和血缘管理，符合学术文献的引用规范
2. **统一持久化**：使用 PowerContext 的 SQLite Profile，自动处理连接池、事务、WAL 日志
3. **全文搜索**：FTS5 提供高效的中文分词和全文检索能力
4. **向量索引**：sqlite-vec 提供本地向量索引，无需外部向量数据库
5. **混合检索**：RRF 融合算法结合关键词和语义搜索，提升检索质量

### 为什么保留旧版 database.py？

论文关系（引用、语义相似、共同作者）的存储和查询暂时仍使用旧版 `database.py`。未来计划将关系也建模为 PowerContext Artifact 或 Source。

### 为什么使用同步包装器？

Flask 路由默认是同步的，而 PowerContext 的 SQLite Profile 是异步的。`SyncPaperStore` 提供同步接口，内部使用 `asyncio.run()` 桥接异步调用，减少重构工作量。

## ❓ 常见问题

### 端口被占用

```powershell
python -m flask --app app run --port 5001
```

或修改 `app.py` 最后一行：`app.run(debug=True, port=5001)`

### 使用本地模型（Ollama）

1. 安装 [Ollama](https://ollama.ai/)
2. 拉取模型：`ollama pull qwen2.5:7b`
3. 修改 `.env`：

```ini
OPENAI_API_KEY=ollama
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_MODEL=qwen2.5:7b
```

### 数据备份

所有数据存储在 `data/` 目录下，直接备份该目录即可：
- `data/papers_powercontext.db` — PowerContext Artifact 数据库（论文元数据）
- `data/papers.db` — 旧版数据库（论文关系）
- `data/vectors.db` — 向量索引
- `data/uploads/` — PDF 文件

### 如何从旧版本迁移？

运行迁移脚本：
```powershell
python migrate_to_powercontext.py
```

迁移完成后，新数据会存入 `papers_powercontext.db`，旧数据库 `papers.db` 保留用于关系查询。

### PowerContext 的异步特性会影响性能吗？

不会。`SyncPaperStore` 使用 `asyncio.run()` 在每次调用时创建事件循环，对于个人使用场景（~100 篇论文），性能开销可忽略。未来可以升级为全异步 Flask 应用（使用 `async def` 路由）。

## 📝 后续计划

- [ ] 将论文关系迁移到 PowerContext Source 系统
- [ ] 使用 Topic Memory Artifact 替代简单的 topic_cluster 字符串
- [ ] 实现 Experience Artifact 记录研究模式和发现
- [ ] 支持 BibTeX 导入/导出
- [ ] 论文笔记功能（使用 Memory Artifact）
- [ ] 自动从 ArXiv/Semantic Scholar 拉取论文元数据（使用 Source Adapter）
- [ ] 更多可视化选项（时间线视图、作者网络）
- [ ] 导出为 LaTeX / Word 格式
- [ ] 全异步 Flask 应用（移除 SyncPaperStore 包装器）

## 📄 许可证

Apache License 2.0

## 🙏 致谢

本项目基于 [PowerContext](https://github.com/oceanbase/powercontext) 框架构建，感谢 PowerContext 团队提供的优秀基础设施。
