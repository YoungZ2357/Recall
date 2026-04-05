"""Entry point for ``python -m app.mcp``."""

import logging
import sys

# Route all logging to stderr so stdout stays clean for stdio transport.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)

from app.mcp.server import mcp  # noqa: E402

mcp.run(transport="stdio")
