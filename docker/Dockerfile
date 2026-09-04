FROM python:3.10-slim AS builder

ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:/root/.local/bin:${PATH}"
ENV UV_LINK_MODE=copy

WORKDIR /app

RUN python -m pip install --no-cache-dir -i "${PIP_INDEX_URL}" uv

COPY pyproject.toml uv.lock README.md /app/

RUN uv venv "${VIRTUAL_ENV}"

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --active --no-dev --no-install-project

FROM python:3.10-slim AS runtime

ARG APT_MIRROR=mirrors.aliyun.com

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /app

RUN python -m pip uninstall -y pip \
    && sed -i "s@deb.debian.org@${APT_MIRROR}@g; s@security.debian.org@${APT_MIRROR}@g" /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        ffmpeg \
        tzdata \
        libgomp1 \
    && ln -snf /usr/share/zoneinfo/${TZ} /etc/localtime \
    && echo "${TZ}" > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
COPY csrcqsf/ /app/csrcqsf/

RUN mkdir -p \
    /app/logs/app \
    /app/logs/vector_db \
    /app/temp \
    /app/state/vector_db/patch_tokens \
    /app/state/reconstruction

CMD ["python", "-m", "csrcqsf"]
