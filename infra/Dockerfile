FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/backend/src

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend backend

EXPOSE 8000

CMD ["uvicorn", "devlog_mcp_server.main:app", "--app-dir", "backend/src", "--host", "0.0.0.0", "--port", "8000"]
