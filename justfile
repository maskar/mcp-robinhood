DEFAULT_SERVER := "mcp-gateway"
DEPLOY_PATH := "/opt/mcp-robinhood"

# Run locally (stdio)
run *ARGS:
    uv run mcp-robinhood {{ARGS}}

# Run locally (HTTP)
serve:
    MCP_TRANSPORT=http uv run mcp-robinhood

# Dev mode (inspector)
dev:
    uv run fastmcp dev src/mcp_robinhood/server/app.py

# Deploy to VPS
deploy: (deploy-to DEFAULT_SERVER)

deploy-to server:
    rsync -avz --delete \
        --exclude='.git' \
        --exclude='.venv' \
        --exclude='__pycache__' \
        --exclude='*.pyc' \
        --exclude='.DS_Store' \
        --exclude='.env' \
        --exclude='logs/' \
        --exclude='*.egg-info' \
        --exclude='test_local.py' \
        ./ {{server}}:{{DEPLOY_PATH}}/

deploy-dry:
    rsync -avzn --delete \
        --exclude='.git' \
        --exclude='.venv' \
        --exclude='__pycache__' \
        --exclude='*.pyc' \
        --exclude='.DS_Store' \
        --exclude='.env' \
        --exclude='logs/' \
        --exclude='*.egg-info' \
        --exclude='test_local.py' \
        ./ {{DEFAULT_SERVER}}:{{DEPLOY_PATH}}/

# Build container on VPS
build:
    ssh {{DEFAULT_SERVER}} "cd {{DEPLOY_PATH}} && podman build -t mcp-robinhood:latest -f Containerfile ."

# Start container on VPS
up:
    ssh {{DEFAULT_SERVER}} "podman run -d \
        --name mcp-robinhood \
        --restart unless-stopped \
        -p 127.0.0.1:8081:8080 \
        --env-file {{DEPLOY_PATH}}/.env \
        -e MCP_TRANSPORT=http \
        -e MCP_HOST=0.0.0.0 \
        -e MCP_PORT=8080 \
        --dns 1.1.1.1 --dns 8.8.8.8 \
        -v mcp-robinhood_robinhood-tokens:/home/app/.tokens \
        -v mcp-robinhood_fastmcp-oauth:/home/app/.local/share/fastmcp/oauth-proxy \
        --memory 512m \
        --cpus 0.5 \
        mcp-robinhood:latest"

# Stop container on VPS
down:
    ssh {{DEFAULT_SERVER}} "podman stop mcp-robinhood && podman rm mcp-robinhood"

# Restart container on VPS (recreate from new image)
restart:
    ssh {{DEFAULT_SERVER}} "podman stop mcp-robinhood && podman rm mcp-robinhood"
    just up

# View logs on VPS
logs:
    ssh {{DEFAULT_SERVER}} "podman logs -f mcp-robinhood"

# Check status on VPS
status:
    ssh {{DEFAULT_SERVER}} "podman ps -a --filter name=mcp-robinhood"
