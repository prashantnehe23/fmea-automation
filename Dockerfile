# B-042 / ADR-026: one image with the API and the built frontend. Run it with docker-compose.yml.
FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    FMEA_DATA_DIR=/data \
    FMEA_STATIC_DIR=/app/static
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY agents/ agents/
COPY api/ api/
COPY core/ core/
COPY memory/ memory/
COPY workflows/ workflows/
COPY --from=web /web/dist/ static/
RUN useradd --system --uid 10001 fmea && mkdir /data && chown fmea /data
USER fmea
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/health').status == 200 else 1)"
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
