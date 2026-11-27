FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

# Install FFmpeg, Node.js (for yt-dlp JS challenge solver), and OpenCV runtime libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    nodejs \
    libgl1 \
    libglib2.0-0 \
    fontconfig \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.cloud.txt ./requirements.cloud.txt
RUN pip install --no-cache-dir -r requirements.cloud.txt

COPY backend/app ./app

RUN mkdir -p /app/workspace && chmod -R 777 /app/workspace

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
