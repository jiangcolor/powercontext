# 实验记录本 (Lab Notebook)

基于 **seekdb** 向量检索 + **PowerContext** 项目记忆的智能实验记录与检索系统。

## 功能特性

- **实验记录** — 结构化记录每次实验的参数、指标、结果和分析笔记
- **语义搜索** — 用自然语言搜索实验历史，seekdb 向量检索秒级定位相关实验
- **项目追踪** — PowerContext 记住每个科研项目的目标、状态和关键决策，跨会话持久化
- **实验对比** — 选择多个实验，自动生成参数与结果对比表，快速找到最优配置

## 技术架构

```
┌─────────────────────────────────────────────────┐
│  Frontend (Static HTML/CSS/JS)                   │
│  首页 | 实验记录 | 语义搜索 | 项目管理 | 实验对比  │
└──────────────────────┬──────────────────────────┘
                       │ HTTP
┌──────────────────────▼──────────────────────────┐
│  Backend (Python FastAPI)                        │
│  /api/experiments  /api/search  /api/projects    │
└────────┬─────────────────────────────┬──────────┘
         │                             │
    ┌────▼────┐                  ┌─────▼─────┐
    │ seekdb  │                  │PowerContext│
    │ (pyseekdb)│                │ (HTTP API) │
    │ 向量检索  │                  │ 项目记忆    │
    └─────────┘                  └───────────┘
```

### 技术分工

| 组件 | 职责 |
|:---|:---|
| **seekdb (pyseekdb)** | 存储实验记录的文本 embedding；提供语义相似度检索；支持按项目过滤 |
| **PowerContext** | 管理科研项目元信息（目标、状态、关键决策）；跨会话记忆持久化；提供上下文感知的项目追踪 |

## 快速开始

### 前置条件

- Python 3.11+
- Node.js 18+（仅开发时需要）
- PowerContext 服务（可选，项目追踪功能依赖）

### 1. 安装后端依赖

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，配置 seekdb 路径和 PowerContext 地址
```

### 3. 启动 PowerContext（可选）

```bash
# 如果尚未安装 PowerContext
uv tool install --force "powercontext[cli,server]==1.4.1"
powercontext config init --language zh --output .env
powercontext server run --env-file .env
```

### 4. 启动后端服务

```bash
cd backend
python run.py
# 服务启动在 http://localhost:8080
```

### 5. 打开前端

直接用浏览器打开 `frontend/index.html`，或使用任意静态文件服务器：

```bash
cd frontend
python -m http.server 3000
# 访问 http://localhost:3000
```

## 验证样例

详见 [docs/validation.md](docs/validation.md)。

## 项目结构

```
qoder/
├── README.md                    # 本文件
├── backend/
│   ├── requirements.txt         # Python 依赖
│   ├── .env.example             # 环境变量模板
│   ├── run.py                   # 启动入口
│   └── app/
│       ├── config.py            # 配置管理
│       ├── database.py          # seekdb (pyseekdb) 集成
│       ├── powercontext.py      # PowerContext 客户端
│       ├── models.py            # 数据模型
│       └── main.py              # FastAPI 应用
├── frontend/
│   ├── index.html               # 首页
│   ├── experiments.html         # 实验记录页
│   ├── search.html              # 语义搜索页
│   ├── projects.html            # 项目管理页
│   ├── compare.html             # 实验对比页
│   ├── css/style.css            # 样式
│   └── js/api.js                # API 工具函数
└── docs/
    ├── run.md                   # 详细运行说明
    └── validation.md            # 验证样例
```

## License

MIT
