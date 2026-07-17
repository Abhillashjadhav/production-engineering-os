# pm-evals Web backend: the same FastAPI app the tests exercise, no extras.
FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

EXPOSE 8000
# slim has no curl; health-check with the stdlib
HEALTHCHECK --interval=5s --timeout=3s --retries=12 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"]
CMD ["uvicorn", "pm_evals_api.app:app", "--host", "0.0.0.0", "--port", "8000"]
