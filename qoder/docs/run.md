# 运行说明

## 环境要求

| 组件 | 版本要求 | 说明 |
|:---|:---|:---|
| Python | 3.11+ | 后端运行时 |
| seekdb (pyseekdb) | >= 0.1.0 | 向量检索（嵌入式模式） |
| PowerContext | 1.4.1 | 项目记忆（可选，通过 HTTP API 接入） |

## 安装步骤

### 1. 克隆仓库

```bash
git clone <repository-url>
cd qoder
```

### 2. 安装后端依赖

```bash
cd backend
python -m venv .venv

# Linux/macOS
source .venv/bin/activate
# Windows
.venv\Scripts\activate

pip install -r requirements.txt
```

### 3. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```ini
# seekdb 嵌入式数据库路径
SEEKDB_PATH=./data/experiments.db

# PowerContext 服务地址（如果已启动）
POWERCONTEXT_URL=http://127.0.0.1:8000
POWERCONTEXT_SCOPE=lab-notebook

# 后端服务端口
HOST=0.0.0.0
PORT=8080
```

### 4. 启动 PowerContext 服务（可选）

项目追踪功能依赖 PowerContext。如果不需要该功能，可以跳过此步骤。

```bash
# 安装 PowerContext
uv tool install --force "powercontext[cli,server]==1.4.1"

# 初始化配置
powercontext config init --language zh --output .env

# 启动服务
powercontext server run --env-file .env
```

PowerContext 默认运行在 `http://127.0.0.1:8000`。

### 5. 启动后端服务

```bash
cd backend
python run.py
```

后端启动后会打印：
```
INFO:     Uvicorn running on http://0.0.0.0:8080
```

### 6. 启动前端

**方式一：直接打开文件**

用浏览器打开 `frontend/index.html`。

**方式二：使用静态文件服务器**

```bash
cd frontend
python -m http.server 3000
# 访问 http://localhost:3000
```

## 部署到 Qoder Sites

本项目前端为纯静态文件，可直接部署到 Qoder Sites：

1. 在 Qoder 中创建 Sites 项目
2. 将 `frontend/` 目录下的所有文件上传
3. 配置后端 API 地址（修改 `frontend/js/api.js` 中的 `API_BASE`）
4. 发布站点

## 故障排查

### seekdb 初始化失败

- 确保 `SEEKDB_PATH` 目录可写
- 首次启动会自动创建数据库文件

### PowerContext 连接失败

- 检查 PowerContext 服务是否已启动：`curl http://127.0.0.1:8000/health`
- 确认 `.env` 中的 `POWERCONTEXT_URL` 地址正确
- 项目追踪功能会降级为不可用，其他功能不受影响

### 前端无法连接后端

- 确保后端运行在 `http://localhost:8080`
- 检查浏览器控制台是否有 CORS 错误
- 如果部署到 Qoder Sites，需要修改 `api.js` 中的 `API_BASE` 为后端实际地址
