"""MCP server package initialization"""

from mcp_robinhood.config import load_config
from mcp_robinhood.server.app import create_mcp_server

# Create server instance with default configuration
server = create_mcp_server(load_config())

__all__ = ["create_mcp_server", "server"]
