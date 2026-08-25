# Use official Python runtime as base image
FROM python:3.11-slim

# Set working directory in container
WORKDIR /app

# Copy project files
COPY . .

# Install dependencies from pyproject.toml
RUN pip install --no-cache-dir -e .

# Run the BSC bot
CMD ["python3", "bsc_main.py"]
