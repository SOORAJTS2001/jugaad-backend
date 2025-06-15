# Use a minimal Python image
FROM python:3.12-slim

# Set working directory inside the container
WORKDIR /app

# Prevent Python from writing .pyc files
ENV PYTHONDONTWRITEBYTECODE=1
# Prevent Python from buffering stdout/stderr
ENV PYTHONUNBUFFERED=1

# Set default port value and expose it
ARG PORT=8000
ENV PORT=${PORT}
EXPOSE ${PORT}

# Install system dependencies
RUN apt-get update \
    && apt-get install -y curl build-essential \
    && apt-get clean

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 - \
    && ln -s /root/.local/bin/poetry /usr/local/bin/poetry

# Disable Poetry virtualenv creation
RUN poetry config virtualenvs.create false

# Copy dependency declarations first to cache Docker layers
COPY pyproject.toml poetry.lock ./

# Install dependencies (excluding dev, not installing package itself)
RUN poetry install --no-root

# Copy the application code
COPY . .

# Run FastAPI using uvicorn
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
