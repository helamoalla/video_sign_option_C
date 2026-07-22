FROM python:3.11.15-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        ffmpeg \
        fonts-dejavu-core \
        fonts-noto-core \
        git \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        xauth \
        xvfb \
    && update-ca-certificates

ARG PIP_VERSION=26.1.2

COPY requirements.txt /app/requirements.txt
COPY requirements.lock.txt /app/requirements.lock.txt

RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install \
        "pip==${PIP_VERSION}" \
    && python -m pip install \
        --requirement /app/requirements.lock.txt \
    && python -m pip check

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    python -m playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        xauth \
        xvfb \
    && mkdir -p /tmp/.X11-unix \
    && chmod 1777 /tmp/.X11-unix

COPY . /app

RUN mkdir -p \
        /app/outputs \
        /app/uploads \
        /app/temp \
    && useradd \
        --create-home \
        --shell /bin/bash \
        appuser \
    && chown -R appuser:appuser \
        /app \
        /ms-playwright

USER appuser

EXPOSE 8000

HEALTHCHECK \
    --interval=30s \
    --timeout=10s \
    --start-period=60s \
    --retries=3 \
    CMD curl --fail http://localhost:8000/ready || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]