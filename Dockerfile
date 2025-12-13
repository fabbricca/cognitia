FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
  libportaudio2 \
  portaudio19-dev \
  git \
  && rm -rf /var/lib/apt/lists/*

RUN pip install uv

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY web/ ./web/

# Install dependencies (API-only, no models needed)
RUN uv sync --extra api --extra cpu --no-dev

# Create user 1000 and give ownership of app directory
RUN useradd -u 1000 -m appuser && chown -R appuser:appuser /app

USER appuser

# Set environment for uv cache at runtime
ENV UV_CACHE_DIR=/tmp/.uv-cache
ENV HOME=/tmp

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "cognitia.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
