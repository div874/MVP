import sys
import os
import json
import argparse
import requests
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

XKIRO_API_KEY = os.getenv("XKIRO_API_KEY", "your_api_key_here")
XKIRO_BASE_URL = os.getenv("XKIRO_BASE_URL", "https://api.xkiro.ai/v1").rstrip("/")
DEFAULT_MODEL = os.getenv("MODEL_NAME", "qwen/qwen3.8-omni-flash:free")

def make_request(method: str, endpoint: str, payload: dict = None):
    # Ensure endpoint starts with a slash
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    
    url = f"{XKIRO_BASE_URL}{endpoint}" if not endpoint.startswith("http") else endpoint

    headers = {
        "Authorization": f"Bearer {XKIRO_API_KEY}",
        "Content-Type": "application/json"
    }

    print(f"Making {method.upper()} request to: {url}")
    if XKIRO_API_KEY == "your_api_key_here":
        print("⚠️ Warning: XKIRO_API_KEY is set to default placeholder. Replace with your key in .env file.")

    try:
        if method.upper() == "GET":
            response = requests.get(url, headers=headers, timeout=30)
        elif method.upper() == "POST":
            response = requests.post(url, headers=headers, json=payload or {}, timeout=60)
        else:
            print(f"Error: Unsupported HTTP method '{method}'")
            return None

        print(f"Status Code: {response.status_code}")
        try:
            res_json = response.json()
            print("\nResponse Payload:")
            print(json.dumps(res_json, indent=2))
            return res_json
        except Exception:
            print("Response Text:", response.text)
            return response.text

    except Exception as e:
        print(f"Error executing request: {e}")
        return None

def main():
    parser = argparse.ArgumentParser(description="XKIRO API CLI Helper")
    parser.add_argument("method", help="HTTP Method (GET or POST)")
    parser.add_argument("endpoint", help="API Endpoint (e.g. /v1/status or /v1/chat/completions)")
    parser.add_argument("--payload", help="JSON payload string for POST requests", default=None)

    args = parser.parse_args()

    payload_dict = None
    if args.payload:
        try:
            payload_dict = json.loads(args.payload)
        except json.JSONDecodeError as err:
            print(f"Error parsing JSON payload: {err}")
            sys.exit(1)

    make_request(args.method, args.endpoint, payload_dict)

if __name__ == "__main__":
    main()
