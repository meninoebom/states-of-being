"""Shared test setup.

Importing the FastAPI app pulls in app.config, whose Settings requires
REPLICATE_API_TOKEN. CI does not set it (the token is a runtime secret, never
needed by these tests since no real Replicate call is made), so provide a dummy
before any app import happens.
"""

import os

os.environ.setdefault("REPLICATE_API_TOKEN", "test-token")
