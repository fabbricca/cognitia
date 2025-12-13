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

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "cognitia.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
