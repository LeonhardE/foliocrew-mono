FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
WORKDIR /app

COPY services/workspace-admission/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --system --uid 10001 --create-home appuser
COPY services/workspace-admission/main.py services/workspace-admission/smoke_server.py ./

USER appuser
EXPOSE 8080
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT} smoke_server:app"]
