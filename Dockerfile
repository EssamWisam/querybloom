FROM python:3.12-slim
WORKDIR /workspace/querybloom

# Install Node.js 22 from official Node image
COPY --from=node:22-bookworm-slim /usr/local/bin /usr/local/bin
COPY --from=node:22-bookworm-slim /usr/local/lib/node_modules /usr/local/lib/node_modules

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 1. Install Node dependencies (cached layer)
COPY webapp/package*.json /workspace/querybloom/webapp/
RUN cd /workspace/querybloom/webapp && npm install

# 2. Install Python dependencies (cached layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-cache --no-install-project

# 3. Copy application code
COPY . /workspace/querybloom

# 4. Initial frontend build
ENV BASE_PATH=/querybloom
RUN cd /workspace/querybloom/webapp && npm run build

# Expose port
EXPOSE 8000

# Set environment path for uv and python
ENV PATH="/workspace/querybloom/.venv/bin:$PATH"
ENV PYTHONPATH="/workspace:$PYTHONPATH"

RUN chmod +x /workspace/querybloom/start.sh

# Run startup script that auto-watches both frontend (.svelte) and backend (.py) files live
CMD ["/workspace/querybloom/start.sh"]
