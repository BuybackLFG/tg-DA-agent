FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for pandas/matplotlib
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN pip install --no-cache-dir poetry

# Copy dependency files
COPY pyproject.toml ./

# Install dependencies
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --no-root

# Copy source code
COPY src/ ./src/
COPY sandbox/ ./sandbox/

# Run
CMD ["python", "-m", "src.main"]
