FROM python:3.11-alpine

WORKDIR /app

# Copy only generated_code content (use generated_code as build context)
COPY . /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

EXPOSE 8080

# Serve generated frontend output only
CMD ["sh", "-c", "python -m http.server ${PORT:-8080} --directory /app/frontend_engineer"]
