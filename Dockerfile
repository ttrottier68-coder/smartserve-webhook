FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY app.py .

# Expose port
EXPOSE 5000

# Run with gunicorn for production
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "app:app"]
