"""Railway startup script for Song Blender API."""

import os
import sys


def main():
    if not os.environ.get("REPLICATE_API_TOKEN"):
        print("ERROR: REPLICATE_API_TOKEN environment variable is required")
        sys.exit(1)

    port = int(os.environ.get("PORT", "8000"))

    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
