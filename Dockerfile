FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY app.py .

# Expose port (Render sets $PORT at runtime)
EXPOSE 10000

# Run with gunicorn on Render's $PORT
CMD ["sh", "-c", "gunicorn -w 2 -b 0.0.0.0:${PORT:-10000} app:app"]
