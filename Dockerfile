# Use official Python runtime as base
FROM python:3.12-slim

# Install system deps, including ffmpeg
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy project files
COPY . .

# Install Python deps
RUN pip install --no-cache-dir -r requirements.txt

# Expose port (Render assigns dynamically, but good practice)
EXPOSE $PORT

# Command for API (Render overrides with Start Command)
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "$PORT"]