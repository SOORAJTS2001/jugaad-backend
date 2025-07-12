# Use a minimal Python image
FROM python:3.12-slim

# Set working directory inside the container
WORKDIR /app

# Prevent Python from writing .pyc files
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update \
    && apt-get install -y curl build-essential \
    && apt-get clean

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 - \
    && ln -s /root/.local/bin/poetry /usr/local/bin/poetry

# Disable Poetry virtualenv creation
RUN poetry config virtualenvs.create false

# Copy dependency declarations
COPY pyproject.toml poetry.lock ./

# Install dependencies
RUN poetry install --no-root --no-interaction --no-ansi

# Copy source code
COPY . .

# Default port Render provides
ENV PORT=8000

# Explicitly expose the port
EXPOSE $PORT

# Run FastAPI via Uvicorn (Render passes PORT automatically)
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
