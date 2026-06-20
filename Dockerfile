# Образ только для бота. Панель 3x-UI остаётся снаружи (бот ходит в неё по
# XUI_API_URL по сети) — её в контейнер НЕ заворачиваем.
FROM python:3.12-slim

# Логи сразу в stdout (видно в `docker compose logs`), без .pyc
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Сначала зависимости — слой кешируется, пока requirements.txt не меняется
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Затем код. .env, users.db, backups в образ НЕ попадают (см. .dockerignore) —
# секреты приходят через env_file, данные монтируются томами в рантайме.
COPY src/ ./src/
COPY migrate_features.py .

# CWD = /app, поэтому sqlite:///users.db -> /app/users.db, backups -> /app/backups
CMD ["python", "src/app.py"]
