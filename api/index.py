"""
Vercel Serverless Entrypoint for RecoverAI.
Exposes the FastAPI 'app' instance for Vercel's Python runtime.
"""

import sys
from pathlib import Path

# Add project root to sys.path so server.py and src/* can be imported
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from server import app
