"""Start the private studio API: python -m backend.serve [--host 0.0.0.0]."""
import argparse
import os
from pathlib import Path
import secrets
from dotenv import load_dotenv

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    env_path = Path(".env")
    load_dotenv(env_path)
    if not os.getenv("XR3D_API_TOKEN"):
        token = secrets.token_urlsafe(32)
        with env_path.open("a", encoding="utf-8") as stream:
            stream.write(f"\nXR3D_API_TOKEN={token}\n")
        os.environ["XR3D_API_TOKEN"] = token
        print("A server access token was saved to .env. Enter that token in the app Settings.")
    if not (os.getenv("XR3D_LOCAL_COMMAND") or os.getenv("FAL_KEY") or os.getenv("MESHY_API_KEY")):
        print("No server inference key/runtime configured. Set XR3D_LOCAL_COMMAND, FAL_KEY, or MESHY_API_KEY; Meshy users can also supply their own key in the app.")
    import uvicorn
    uvicorn.run("backend.main:app", host=args.host, port=args.port, workers=1)

if __name__ == "__main__":
    main()
