FROM python:3.11-slim

# System tools needed by the search/index engines
RUN apt-get update && apt-get install -y --no-install-recommends \
    fd-find \
    ripgrep \
    git \
    && rm -rf /var/lib/apt/lists/*

# Symlink fd-find → fd (Debian packages it as fdfind)
RUN ln -sf /usr/bin/fdfind /usr/bin/fd

WORKDIR /app

# Install Python deps first (cache layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the codebase
COPY . .

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "codeengine.app:app", "--host", "0.0.0.0", "--port", "8000"]
