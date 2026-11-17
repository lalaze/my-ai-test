# 代码题的默认环境。题目需要额外依赖时，在题目目录下放 environment/Dockerfile + compose.yaml
FROM python:3.12-bookworm

RUN pip install --no-cache-dir "pytest>=8,<10" \
 && useradd --create-home --shell /bin/bash agent \
 && mkdir -p /workspace \
 && chown agent:agent /workspace

WORKDIR /workspace
