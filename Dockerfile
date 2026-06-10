# Use Microsoft's official Playwright Python base image (contains all browsers and OS dependencies)
FROM mcr.microsoft.com/playwright/python:v1.45.0-jammy

# Set up app directory
WORKDIR /app

# Install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Command to start the bot
CMD ["python", "bot.py"]
