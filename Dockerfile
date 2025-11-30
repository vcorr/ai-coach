FROM python:3.13-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Copy dependency files first (for caching)
COPY pyproject.toml uv.lock ./

# Install dependencies (no dev dependencies, compile bytecode)
RUN uv sync --frozen --no-dev --compile-bytecode

# Copy application code
COPY main.py ./

# Expose port (Cloud Run uses PORT env var, default 8080)
EXPOSE 8080

# Run the application
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]

