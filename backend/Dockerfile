# backend/Dockerfile
# 使用轻量级的 Python 3.10 基础镜像（LangChain 兼容性好）
FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 先复制依赖文件，利用 Docker 缓存机制加速构建
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制全部代码
COPY . .

# 暴露 FastAPI 默认端口
EXPOSE 8000

# 启动命令 (生产环境建议把 main:app 换成你的实际入口，如 app.main:app)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]