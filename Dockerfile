FROM python:3.12-slim
WORKDIR /srv
# DejaVu Sans has Georgian glyphs — used for the text we add to derivative sheets.
# Tesseract (Georgian + English) reads room labels on scans, which have no text layer (app/ocr.py).
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core \
        tesseract-ocr tesseract-ocr-kat tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY harness ./harness
COPY tests ./tests
EXPOSE 8090
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]
