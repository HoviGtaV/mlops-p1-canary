FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/src

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt
COPY requirements-fast.txt .
RUN pip install -r requirements-fast.txt

COPY src/ /app/src/
COPY analysis/ /app/analysis/
COPY tests/ /app/tests/

CMD ["python", "-c", "print('set a command in docker-compose.yml')"]
