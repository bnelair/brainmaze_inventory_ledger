# ─── Stage 1: base ───────────────────────────────────────────────────────────
FROM python:3.11-slim AS base

# System dependencies: git (data sync), git-crypt (encrypted repos),
# openssh-client (SSH key-based Git auth), curl (healthcheck).
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

# Copy application source
COPY src/ ./src/

# Default data & reports directories (overridden via volume mounts)
RUN mkdir -p /app/data /app/reports

# Streamlit configuration (disable telemetry, set server options)
RUN mkdir -p /root/.streamlit
COPY <<'EOF' /root/.streamlit/config.toml
[server]
headless = true
address = "0.0.0.0"
port = 8501
enableCORS = false
enableXsrfProtection = true

[browser]
gatherUsageStats = false

[theme]
primaryColor = "#1e4078"
backgroundColor = "#FFFFFF"
secondaryBackgroundColor = "#f0f5ff"
textColor = "#0d0d0d"
EOF

# Environment variable defaults (overridden at runtime)
ENV DATA_DIR=/app/data \
    REPORTS_DIR=/app/reports \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "src/app.py"]
