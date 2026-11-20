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
# PIP_INDEX_URL 可切换镜像源：国内 ECS 构建时用阿里云源，境外 CI 用官方源
ARG PIP_INDEX_URL=https://pypi.org/simple
COPY requirements.txt .
RUN pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" \
        --extra-index-url https://pypi.org/simple \
        -r requirements.txt

# 预热 chromadb 默认向量模型（all-MiniLM-L6-v2），下载约 79MB。
# 必须放在 COPY . . 之前：否则每次改代码都会让这层缓存失效，白白多等几分钟。
# 产物落在 /root/.cache/chroma，容器运行时可直接复用（生产环境另有只读卷覆盖此目录）。
# 下载失败不阻塞构建，运行时再尝试。
RUN python -c "import chromadb; c = chromadb.PersistentClient(path='/tmp/warmup'); c.get_or_create_collection('warmup').upsert(ids=['1'], documents=['warmup'])" \
    || echo "WARN: 向量模型预热失败，运行时将尝试重新下载"

# 复制业务代码（.dockerignore 已排除缓存/本地环境）
COPY . .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8000/ || exit 1

# 状态（对话历史、HITL 中断现场）保存在进程内存中，因此固定单 worker
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
