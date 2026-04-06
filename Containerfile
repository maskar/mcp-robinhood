FROM python:3.13-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Create non-root user
RUN useradd -m -s /bin/bash app
USER app
WORKDIR /home/app/mcp-robinhood

# Install dependencies first (cache layer)
COPY --chown=app:app pyproject.toml uv.lock LICENSE README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy source
COPY --chown=app:app src/ src/
RUN uv sync --frozen --no-dev

# Session pickle volume
VOLUME /home/app/.tokens

EXPOSE 8080

ENTRYPOINT ["uv", "run", "mcp-robinhood"]
