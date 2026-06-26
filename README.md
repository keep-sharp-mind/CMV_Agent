# CMV Agent

前后端协同的 AI Agent 系统

## 项目结构

```
CMV_Agent/
├── backend/               # Python 后端
│   ├── app.py            # Flask API 服务
│   ├── agent.py          # Agent 核心逻辑
│   ├── model.py          # 大模型 API 调用
│   └── requirements.txt  # Python 依赖
└── frontend/             # React 前端
    ├── src/
    │   ├── App.jsx       # 主组件
    │   ├── api.js       # API 调用
    │   └── index.css    # 样式
    └── package.json     # Node 依赖
```

## 快速开始

### 后端设置

1. 进入后端目录并安装依赖：
```bash
cd backend
pip install -r requirements.txt
```

2. 配置环境变量，复制 `.env.example` 为 `.env` 并填入你的 API Key：
```bash
cp .env.example .env
```

3. 启动后端服务：
```bash
python app.py
# 或
flask run --host=0.0.0.0 --port=5000
```

### 前端设置

1. 进入前端目录并安装依赖：
```bash
cd frontend
npm install
```

2. 启动开发服务器：
```bash
npm run dev
```

3. 访问 http://localhost:3000

## API 接口

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/chat` | POST | 发送消息并获取响应 |
| `/api/chat/stream` | POST | 流式对话 |
| `/api/models` | GET | 获取可用模型列表 |
| `/api/model/set` | POST | 设置当前模型 |
| `/api/conversation/history` | GET | 获取对话历史 |
| `/api/conversation/clear` | POST | 清空对话 |
| `/api/health` | GET | 健康检查 |

## 支持的模型

当前支持阿里云 Qwen 系列模型（OpenAI 兼容格式）：
- qwen-turbo
- qwen-plus
- qwen-max

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `OPENAI_API_KEY` | API 密钥 | - |
| `OPENAI_API_BASE` | API 基础 URL | https://dashscope.aliyuncs.com/compatible-mode/v1 |
| `DEFAULT_MODEL` | 默认模型 | qwen-turbo |
| `PORT` | Flask 端口 | 5000 |
