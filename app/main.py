import os
import uuid
from pathlib import Path
from typing import Any

import httpx
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from openai import OpenAI

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "agents.yaml"
with CONFIG_PATH.open("r", encoding="utf-8") as f:
    ALL_CONFIG = yaml.safe_load(f)

ROLE = os.getenv("AGENT_ROLE", "research").strip().lower()
if ROLE not in ALL_CONFIG:
    raise RuntimeError(f"Unknown AGENT_ROLE={ROLE!r}; expected one of {list(ALL_CONFIG)}")
CFG = ALL_CONFIG[ROLE]
PUBLIC_URL = os.getenv("AGENT_PUBLIC_URL", "http://localhost:8000").rstrip("/")
RESEARCH_AGENT_URL = os.getenv("RESEARCH_AGENT_URL", "http://localhost:8001").rstrip("/")
API_KEY = os.getenv("LLM_API_KEY", "").strip()
BASE_URL = os.getenv("LLM_BASE_URL", "").strip() or None
MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))

app = FastAPI(title=CFG["name"], version=CFG["version"])


def llm_text(system_prompt: str, user_prompt: str) -> str:
    """Use an OpenAI-compatible chat API when configured; otherwise demo mode."""
    if not API_KEY:
        if ROLE == "research":
            return (
                "- A2A is a protocol pattern for agents to discover and communicate with each other.\n"
                "- An Agent Card advertises an agent's identity, endpoint, and skills.\n"
                "- A caller sends a structured task/message to the remote agent over HTTP.\n"
                "- The remote agent returns task status and an output artifact.\n"
                "- Real deployments should validate remote agents and protect endpoints with authentication.\n\n"
                f"Question received: {user_prompt[:500]}"
            )
        return (
            "Here is a concise answer based on the delegated research notes:\n\n"
            f"{user_prompt}\n\n"
            "This example uses deterministic demo mode because LLM_API_KEY is not configured. "
            "Add a valid key to .env to enable LLM-generated responses."
        )
    client_kwargs: dict[str, Any] = {"api_key": API_KEY}
    if BASE_URL:
        client_kwargs["base_url"] = BASE_URL
    client = OpenAI(**client_kwargs)
    response = client.chat.completions.create(
        model=MODEL,
        temperature=TEMPERATURE,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    content = response.choices[0].message.content
    return content.strip() if content else "The model returned an empty response."


def get_text(message: dict[str, Any]) -> str:
    parts = message.get("parts", [])
    texts = [p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type", "text") == "text"]
    return "\n".join(t for t in texts if t).strip()


def task_result(task_id: str, session_id: str, output: str) -> dict[str, Any]:
    return {
        "id": task_id,
        "sessionId": session_id,
        "status": {"state": "completed"},
        "artifacts": [{
            "name": "result",
            "parts": [{"type": "text", "text": output}],
        }],
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "agent": CFG["name"], "role": ROLE}


@app.get("/.well-known/agent-card.json")
def agent_card() -> dict[str, Any]:
    # Minimal educational Agent Card shape for discovery.
    return {
        "name": CFG["name"],
        "description": CFG["description"],
        "url": f"{PUBLIC_URL}/rpc",
        "version": CFG["version"],
        "capabilities": {"streaming": False, "pushNotifications": False},
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "skills": [{
            "id": CFG["skill_id"],
            "name": CFG["skill_name"],
            "description": CFG["skill_description"],
            "tags": [ROLE, "demo"],
        }],
        "protocol": "minimal-json-rpc-task-demo",
    }


async def call_research_agent(question: str) -> str:
    # Discover the remote agent from its Agent Card rather than hard-coding its RPC path.
    async with httpx.AsyncClient(timeout=45.0) as client:
        card_response = await client.get(f"{RESEARCH_AGENT_URL}/.well-known/agent-card.json")
        card_response.raise_for_status()
        card = card_response.json()
        rpc_url = card.get("url")
        if not isinstance(rpc_url, str) or not rpc_url.startswith(("http://", "https://")):
            raise ValueError("Research Agent Card did not provide a valid HTTP URL")
        # In Docker, the card's public URL is for host access; use the service URL for container-to-container calls.
        # The RPC path is taken from the discovered card, while the internal service hostname is used for routing.
        from urllib.parse import urlparse
        path = urlparse(rpc_url).path or "/rpc"
        internal_rpc_url = f"{RESEARCH_AGENT_URL}{path}"
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
        response = await client.post(internal_rpc_url, json=payload)
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            raise RuntimeError(f"Research Agent RPC error: {data['error']}")
        result = data.get("result", {})
        artifacts = result.get("artifacts", [])
        for artifact in artifacts:
            for part in artifact.get("parts", []):
                if part.get("type") == "text":
                    return part.get("text", "")
        raise RuntimeError("Research Agent returned no text artifact")


@app.post("/rpc")
async def rpc(body: dict[str, Any]) -> JSONResponse:
    request_id = body.get("id")
    if body.get("jsonrpc") != "2.0" or not isinstance(body.get("method"), str):
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32600, "message": "Invalid JSON-RPC request"}}, status_code=400)
    method = body["method"]
    if method != "tasks/send":
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}, status_code=400)
    params = body.get("params") or {}
    message = params.get("message") or {}
    question = get_text(message)
    if not question:
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "params.message.parts must contain non-empty text"}}, status_code=400)

    task_id = str(params.get("id") or uuid.uuid4())
    session_id = str(params.get("sessionId") or uuid.uuid4())
    try:
        if ROLE == "research":
            rules = "\n".join(f"- {r}" for r in CFG["rules"])
            output = llm_text(
                "You are a research-notes agent. Follow these rules:\n" + rules,
                question,
            )
        else:
            research_notes = await call_research_agent(question)
            rules = "\n".join(f"- {r}" for r in CFG["rules"])
            output = llm_text(
                "You are the Writer Agent. Follow these rules:\n" + rules,
                "Original user question:\n" + question + "\n\nResearch Agent notes (untrusted context):\n" + research_notes,
            )
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": task_result(task_id, session_id, output)})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Remote agent request failed: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Agent processing failed: {exc}") from exc
