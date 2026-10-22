"""Tiny host-side client for the Writer Agent."""
import json
import sys
import uuid
import urllib.request

question = " ".join(sys.argv[1:]).strip() or "Explain the A2A protocol in simple terms."
payload = {
    "jsonrpc": "2.0",
    "id": str(uuid.uuid4()),
    "method": "tasks/send",
    "params": {
        "id": str(uuid.uuid4()),
        "sessionId": str(uuid.uuid4()),
        "message": {"role": "user", "parts": [{"type": "text", "text": question}]},
    },
}
request = urllib.request.Request(
    "http://localhost:8002/rpc",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(request, timeout=60) as response:
    data = json.load(response)
if "error" in data:
    raise SystemExit(json.dumps(data["error"], indent=2))
for artifact in data.get("result", {}).get("artifacts", []):
    for part in artifact.get("parts", []):
        if part.get("type") == "text":
            print(part.get("text", ""))
