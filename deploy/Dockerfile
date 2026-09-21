# IELTS Buddy · Web 后端 Dockerfile
#
# 构建：
#   docker build -f deploy/Dockerfile -t ielts-web .
#
# 运行（普通）：
#   docker run --rm -p 8000:8000 \
#     -e IELTS_BUDDY_WEB_DB_URL=mysql+pymysql://... \
#     ielts-web
#
# 推荐用 docker-compose（deploy/docker-compose.yml）一键起整套。

FROM python:3.10-slim

# 元数据
LABEL maintainer="ielts-buddy"
LABEL description="IELTS Buddy Web (FastAPI + uvicorn)"

# 系统依赖（whisper.cpp 需要 C 编译器 + ffmpeg）
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        make \
        pkg-config \
        ffmpeg \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
WORKDIR /app

# 先装依赖（利用 Docker 缓存）
COPY pyproject.toml ./
COPY src/ ./src/

# pip 装项目本身（包含 .[web] 额外依赖）
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e ".[web]"

# 端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

# 启动命令
# 注意：用 main:app 不是 app:app
# 不要 --reload（开发时也别用，会破坏 sqlite + 影响 sync）
CMD ["uvicorn", "ielts_buddy.web.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000"]