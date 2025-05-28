# Start with an official Python base image
FROM python:3.11-slim

# Set the working directory inside the container
WORKDIR /app

# Install system dependencies required by Playwright's browsers
RUN apt-get update && apt-get install -y \
    libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the image
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers and their OS dependencies
RUN playwright install --with-deps chromium

COPY .env /app/.env

COPY ./scraper_assistant /app/scraper_assistant

# Copy your application code (the 'app' package) into the image
COPY ./app ./app

# Copy your frontend static files into the image
# This creates a 'static_frontend' directory inside '/app' in the container
COPY ./frontend ./static_frontend 

# Expose the port your API will run on
EXPOSE 8000

# Command to run your application when the container starts
# For FastAPI with Uvicorn:
CMD ["uvicorn", "app.main_api:app", "--host", "0.0.0.0", "--port", "8000"]
