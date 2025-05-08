FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY main.py .
COPY config.yaml .

# Run as non-root user
RUN useradd -m -u 1000 appuser
USER appuser

ENTRYPOINT ["python", "main.py"] 