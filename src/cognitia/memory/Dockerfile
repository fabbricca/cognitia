FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY *.py ./

# Create personas directory
RUN mkdir -p /app/personas

# Set PYTHONPATH to allow absolute imports
ENV PYTHONPATH=/app

# Expose port
EXPOSE 8000

# Run FastAPI server using python -m to enable relative imports
CMD ["python", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
