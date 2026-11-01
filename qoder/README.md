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

## 🚀 快速部署（Windows）

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
cd C:\Users\ouyan\Desktop\oceanbase\powercontext\qoder
```

### 3. 创建虚拟环境（推荐）

```powershell
python -m venv venv
venv\Scripts\activate
```

### 4. 安装依赖

首先安装 PowerContext：

```powershell
pip install -e ..
pip install "powercontext[builtin] @ file:///C:/Users/ouyan/Desktop/oceanbase/powercontext"
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
python app.py --port 5001
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
