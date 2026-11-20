# backend/Dockerfile
# Python 版本必须与生成 requirements.txt 的环境保持一致（本地为 3.13）
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# curl 仅用于容器健康检查
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# 先装依赖，利用 Docker 层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制业务代码（.dockerignore 已排除缓存/本地环境）
COPY . .

# 预热 chromadb 默认向量模型（all-MiniLM-L6-v2）。
# 不预热的话，首次 embedding 会在服务器上联网下载模型，国内 ECS 经常超时导致 RAG 接口 500。
RUN python -c "import chromadb; c = chromadb.PersistentClient(path='/tmp/warmup'); c.get_or_create_collection('warmup').upsert(ids=['1'], documents=['warmup'])" \
    || echo "WARN: 向量模型预热失败，运行时将尝试重新下载"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8000/ || exit 1

# 状态（对话历史、HITL 中断现场）保存在进程内存中，因此固定单 worker
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
