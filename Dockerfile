FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create configuration directory
RUN mkdir -p /app/configuration

# Copy application code
COPY main.py .

# Create non-root user
RUN useradd -m -u 1000 appuser
RUN chown -R appuser:appuser /app

USER appuser

ENTRYPOINT ["python", "main.py"] 