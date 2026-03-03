# Dockerfile for Backend Application
FROM python:3.9-slim

# Set work directory
WORKDIR /app

# Copy application files
COPY backend_engineer/requirements.txt requirements.txt
COPY backend_engineer/app.py app.py

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose the port the app runs on
EXPOSE 5000

# Command to run the application
CMD ["python", "app.py"]