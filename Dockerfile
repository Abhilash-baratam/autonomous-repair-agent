FROM python:3.11-slim

# Install system tools and Git
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first for fast layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Install agent CLI package
RUN pip install -e .

# Set entrypoint to the agent CLI
ENTRYPOINT ["repair-agent"]