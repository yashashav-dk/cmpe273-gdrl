FROM python:3.11-slim
WORKDIR /app
COPY sync/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt
COPY sync/ /app/sync/
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "-m", "sync"]
