FROM python:3.10-slim-bookworm AS base

ENV POETRY_NO_INTERACTION=true \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_VIRTUALENVS_CREATE=true \
    POETRY_CACHE_DIR='/tmp/poetry_cache' \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1


FROM base AS builder
WORKDIR /app

RUN apt-get -qq update && \
    apt-get -qq install -y --no-install-recommends gcc git && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir poetry

COPY pyproject.toml poetry.lock ./
RUN poetry install --no-root --only main -E uvloop

# AI Shield vision model (NudeNet + onnxruntime + OpenCV headless)
COPY requirements-ai.txt ./
RUN .venv/bin/pip install --no-cache-dir -r requirements-ai.txt

ARG USERBOTINDO_ACCESS_TOKEN
COPY ./preinstall.sh ./
RUN chmod +x ./preinstall.sh && ./preinstall.sh && rm -rf $POETRY_CACHE_DIR


FROM base AS runner
WORKDIR /app

ENV VENV_PATH=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

COPY --from=builder $VENV_PATH $VENV_PATH

COPY . .

CMD ["python", "-m", "rinoka"]
