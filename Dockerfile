FROM python:3.12-slim

# Keeps Python from buffering stdout/stderr so logs appear immediately
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy source
COPY . .

# Data directory for the SQLite database (mounted as a Fly volume)
RUN mkdir -p /data
ENV DATABASE_URL=sqlite+aiosqlite:////data/health_bot.db

# Non-root user for security
RUN adduser --disabled-password --gecos "" botuser \
    && chown -R botuser:botuser /app /data
USER botuser

CMD ["python", "-m", "bot.main"]
