# pm-evals Web backend: the same FastAPI app the tests exercise, no extras.
FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml requirements.lock ./
COPY src ./src
# Install the hash-verified, fully pinned runtime closure first, then the app
# itself with no re-resolution — two builds of the same commit install the same
# runtime dependency versions (dogfood F-3). (The setuptools build backend is
# fetched by pip's build isolation and is not itself pinned here.)
RUN pip install --no-cache-dir --require-hashes -r requirements.lock \
 && pip install --no-cache-dir --no-deps .

# The service refuses to chmod pre-existing directories. Seed the dedicated
# named-volume target with owner-only permissions for first production boot.
RUN mkdir -p /data/monitoring && chmod 0700 /data /data/monitoring

EXPOSE 8000
# slim has no curl; health-check with the stdlib
HEALTHCHECK --interval=5s --timeout=3s --retries=12 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"]
CMD ["uvicorn", "pm_evals_api.app:app", "--host", "0.0.0.0", "--port", "8000"]
