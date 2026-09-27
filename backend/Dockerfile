FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# tesseract-ocr: real OCR engine for the edge-ANPR worker (demo scenes);
# ffmpeg: frame extraction from HLS sources for the same worker;
# libgl1/libglib2.0-0: opencv-python-headless runtime libs.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev tesseract-ocr ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

COPY . .

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
