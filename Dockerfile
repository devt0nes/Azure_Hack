FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Agent library core
COPY agent_catalog.py .
COPY agents_router.py .
COPY app.py .
COPY reputation_hook.py .

# Reputation scoring package (merged from reputation-scoring service)
COPY src/ ./src/

# Frontend (if serving static build)
COPY main.jsx .

# Shared catalog
COPY shared/ ./shared/

# Tests (optional — remove in prod image)
COPY tests/ ./tests/
COPY smoke_test.py .

ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]