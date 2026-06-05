FROM python:3.11-slim

# Set system envs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

WORKDIR /code

# Install system dependencies if any are needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy and install python dependencies
COPY ./requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# Copy application backend package
COPY ./backend /code/backend

# Expose port and run server
EXPOSE 8000
CMD uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT
