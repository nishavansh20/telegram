FROM python:3.11-slim

# Install system dependencies: ffmpeg, git, fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-dejavu-core \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code and assets
COPY . .

# Ensure output and references directory exist
RUN mkdir -p output assets/references

ENV PYTHONUNBUFFERED=1

CMD ["python", "telegram_bot.py"]
