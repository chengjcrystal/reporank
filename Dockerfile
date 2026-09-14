# Runtime image for Cloud Run. Serves the FastAPI app + static web/ SPA from
# one process; the 157k-repo search index is fetched at container start from a
# GitHub release asset (too large to bake into the image or commit to git).
FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app app
COPY web web
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

ENV INDEX_PATH=/app/index_snapshot.pkl

CMD ["./entrypoint.sh"]
