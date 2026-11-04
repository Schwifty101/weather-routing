# One image serves the API and the built React app (via WhiteNoise), so hosting is a single service.

# ---- build the frontend ----
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- runtime ----
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_BEHIND_PROXY=true
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=web /web/dist ./frontend_dist
RUN python manage.py collectstatic --noinput

EXPOSE 8000
# Long trips can need several upstream calls (routes, via-point alternatives, weather batches),
# so allow a generous request timeout. Threads let one worker overlap slow upstream I/O.
CMD ["sh", "-c", "gunicorn config.wsgi --bind 0.0.0.0:${PORT:-8000} --workers 2 --threads 4 --timeout 120"]
