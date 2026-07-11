# FROM python:3.11-slim
FROM public.ecr.aws/docker/library/python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

RUN sed -ri \
        's@deb.debian.org/debian@mirrors.aliyun.com/debian@g; s@security.debian.org/debian-security@mirrors.aliyun.com/debian-security@g' \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends git ripgrep curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml README.md langgraph.json ./
COPY app ./app

EXPOSE 8000 2024

CMD ["python", "-m", "app.entrypoint"]
