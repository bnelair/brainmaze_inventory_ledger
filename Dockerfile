# ─── Stage 1: base ───────────────────────────────────────────────────────────
FROM python:3.11-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        git-crypt \
        openssh-client \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ─── Stage 2: python deps ────────────────────────────────────────────────────
FROM base AS deps

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# ─── Stage 3: final image ────────────────────────────────────────────────────
FROM deps AS final

COPY src/ ./src/
COPY .streamlit/ /root/.streamlit/

RUN mkdir -p /app/data /app/reports

ENV DATA_DIR=/app/data \
    REPORTS_DIR=/app/reports \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "src/app.py"]
