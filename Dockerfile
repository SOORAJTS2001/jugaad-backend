# Use a base image with Python
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy pyproject.toml and poetry.lock first to leverage Docker caching
COPY pyproject.toml poetry.lock ./

# Install Poetry and dependencies
RUN pip install poetry
RUN poetry config virtualenvs.create false \
    && poetry install --no-dev --no-root

# Copy the rest of your application code
COPY . .

EXPOSE ${PORT:-8000} # This exposes $PORT if set, otherwise defaults to 8000

# Command to run your FastAPI application
# Use 'exec' form for better signal handling and environment variable expansion
CMD ["/bin/bash", "-c", "uvicorn app:app --host 0.0.0.0 --port $PORT"]

# Alternative using ENTRYPOINT for migrations (more advanced)
# ENTRYPOINT ["/bin/bash", "-c"]
# CMD ["poetry", "run", "python", "migrate.py", "&&", "uvicorn", "your_app_module:app", "--host", "0.0.0.0", "--port", "$PORT"]
# This is more complex and usually better handled with Railway's pre-deploy step or separate services for migrations.
