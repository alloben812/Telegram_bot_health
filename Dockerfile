FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy source
COPY . .

# Non-root user for security
RUN adduser --disabled-password --gecos "" botuser \
    && chown -R botuser:botuser /app
USER botuser

# Render sets PORT env var; run.py reads WEB_PORT
EXPOSE 8000

CMD ["python", "run.py"]
