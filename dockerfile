# Use a lightweight Python image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to cache dependencies
COPY requirements.txt .

# Install Python dependencies globally (no venv)
RUN pip install --no-cache-dir -r requirements.txt

# Copy rest of your app
COPY . .

# Run your bot
CMD ["python", "telegram_bot.py"]
