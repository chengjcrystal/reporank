#!/bin/sh
# Fetches the prebuilt search index snapshot on first boot (it's a derived
# artifact, not source, so it isn't in the image) then starts the server.
set -e

if [ ! -f "$INDEX_PATH" ] && [ -n "$INDEX_SNAPSHOT_URL" ]; then
  echo "downloading search index snapshot..."
  curl -fsSL -o "$INDEX_PATH" "$INDEX_SNAPSHOT_URL"
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8080}"
