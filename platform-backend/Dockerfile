# Multi-stage Dockerfile for Nexus Test Runner
# Build and runtime environment for running tests in Azure Container Instances.

# ========================= BUILDER STAGE ==================================
FROM python:3.11-slim as builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ========================= RUNTIME STAGE ===================================
FROM python:3.11-slim

WORKDIR /app

# Runtime deps for:
# - smoke_test.py (node/npm + frontend tooling)
# - Playwright/Puppeteer browser console capture
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    ca-certificates \
    nodejs \
    npm \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils \
    fonts-liberation \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

# Copy Python dependencies from builder
COPY --from=builder /root/.local /root/.local

ENV PATH=/root/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ENVIRONMENT=test \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Preinstall Playwright + Chromium browser in image so frontend smoke checks
# can run headless without runtime apt/browser bootstrap.
RUN npm install -g playwright && \
    playwright install chromium

COPY . .

# Default command (ACI overrides command, but keep a sane local default).
CMD ["pytest", "/app", "-v", "--tb=short", "--color=yes"]
