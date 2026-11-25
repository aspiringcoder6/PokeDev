FROM python:3.12-slim
WORKDIR /app
COPY services/sandbox/broker/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt python-dotenv
COPY services/sandbox/broker ./broker
COPY services/sandbox/dashboard ./dashboard
COPY services/sandbox/sandbox_entry.py ./
RUN useradd -m -u 1000 broker && mkdir -p /app/broker-state && chown broker:broker /app/broker-state
USER broker
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
CMD ["uvicorn", "sandbox_entry:app", "--host", "0.0.0.0", "--port", "8000"]
