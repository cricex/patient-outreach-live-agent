# ---- Stage 1: Build React frontend ----
FROM node:20-alpine AS frontend-build

WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ .
RUN chmod +x node_modules/.bin/* && npm run build

# ---- Stage 2: Python runtime ----
FROM python:3.12-slim AS runtime

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ app/
COPY prompts/ prompts/
COPY data/ data/

# Copy built frontend from stage 1
COPY --from=frontend-build /build/dist frontend/dist

# Create logs directory
RUN mkdir -p logs

ENV PYTHONUNBUFFERED=1
ENV WEBSITES_PORT=8000

EXPOSE 8000

# Single worker: Voice Live uses in-process call state
CMD ["gunicorn", "app.main:app", \
     "-k", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "1", \
     "--timeout", "120"]
