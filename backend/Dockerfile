FROM python:3.11-slim

# Noto fonts cover Devanagari/Arabic/Hebrew/Thai/CJK for burned-in subtitles.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-liberation \
    fonts-noto-core \
    fonts-noto-extra \
    fonts-noto-cjk \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p data/temp data/output

EXPOSE 5000

# 1 worker: JobStorage is per-process in-memory, so 2 workers 404 on each other's jobs.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--timeout", "600", "--workers", "1", "app:create_app()"]
