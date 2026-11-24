FROM python:3.11-slim

# Install system ffmpeg and git
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Ensure directories exist
RUN mkdir -p temp output assets

EXPOSE 8080

CMD ["python", "bot.py"]
