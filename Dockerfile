FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY app ./app
COPY evals ./evals
COPY migrations ./migrations
# Pin the browser package to the version used for the sandbox profile.
RUN python -m pip install --no-cache-dir '.[postgres,semantic]' playwright==1.63.0 \
    && python -m playwright install --with-deps chromium \
    && apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && useradd --create-home --uid 10001 outreach \
    && mkdir -p /app/.data \
    && chown outreach:outreach /app/.data \
    && rm -rf /var/lib/apt/lists/*

USER outreach
EXPOSE 8000
CMD ["python", "-m", "app.main"]
