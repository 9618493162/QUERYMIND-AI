# syntax=docker/dockerfile:1
# QueryMind AI — production backend image (FastAPI + uvicorn).
#
# Build from the REPOSITORY ROOT so the shared .dockerignore applies:
#   docker build -f backend/Dockerfile -t querymind-backend .
#
# Runs as an unprivileged user, answers /api/health for liveness and starts
# uvicorn on 0.0.0.0 (required inside a container network).

FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# curl powers the container liveness probe; tini forwards signals so uvicorn
# shuts down cleanly on `docker stop`.
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl tini \
    && rm -rf /var/lib/apt/lists/*

# Dependencies first: application edits below do not invalidate this layer.
COPY backend/requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt

# Application code, migrations and operational scripts.
COPY backend/ ./

# Never run as root.
RUN useradd --create-home --shell /usr/sbin/nologin querymind \
    && chown -R querymind:querymind /app
USER querymind

EXPOSE 8001

# Liveness only: the process answers. Readiness (database reachable) is
# /api/health/ready and is what the reverse proxy / orchestrator should use.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8001/api/health >/dev/null || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
