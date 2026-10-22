# Minimal A2A multi-agent sample (Docker + optional LLM)

Two independent HTTP services:
- `research-agent` accepts A2A-style JSON-RPC `tasks/send` requests and returns research notes.
- `writer-agent` discovers the research agent via its Agent Card, calls it over HTTP using JSON-RPC, then writes a final answer.

This is a deliberately small educational implementation of the A2A message/task pattern and Agent Card discovery. It implements a minimal JSON-RPC subset, **not the complete official A2A specification or a conformance-tested SDK implementation**. For production interoperability, use the official SDK: https://github.com/a2aproject/a2a-python

## Requirements
- Docker Desktop with Docker Compose
- Internet for the first image build and (if enabled) LLM API calls

## Run
1. Copy `.env.example` to `.env`.
2. Optional: add your OpenAI-compatible API key. Without a key, deterministic demo responses are used, so you can test the agent-to-agent HTTP flow without spending money.
3. From this directory:

```bash
docker compose up --build
```

4. In another terminal, send a task to the Writer Agent:

```bash
curl -X POST http://localhost:8002/rpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":"demo-1","method":"tasks/send","params":{"id":"task-demo-1","sessionId":"session-demo","message":{"role":"user","parts":[{"type":"text","text":"Explain A2A protocol in 5 simple bullets"}]}}}'
```

5. Inspect agent cards:
- http://localhost:8001/.well-known/agent-card.json
- http://localhost:8002/.well-known/agent-card.json
- Health: http://localhost:8001/health and http://localhost:8002/health

Stop with `Ctrl+C`, then `docker compose down`.

## Configuration
Rules are in `config/agents.yaml`. Each container reads its own `AGENT_ROLE`, selects its section, and loads the role, rules, and skill description from that file. LLM settings are in `.env.example`:
- `LLM_PROVIDER=openai` (OpenAI-compatible API)
- `LLM_API_KEY` (secret; keep `.env` out of source control)
- `LLM_BASE_URL` (optional; e.g. an OpenAI-compatible provider endpoint)
- `LLM_MODEL`
- `LLM_TEMPERATURE`

For a provider that uses a custom OpenAI-compatible endpoint, set `LLM_BASE_URL` to that provider's documented base URL and use its API key. The API key is only sent to the LLM provider, never to the other agent.

## How the flow works
1. The client sends a JSON-RPC `tasks/send` request to Writer Agent.
2. Writer reads the Research Agent URL from `RESEARCH_AGENT_URL` and fetches `/.well-known/agent-card.json`.
3. Writer sends a second `tasks/send` JSON-RPC request to Research Agent.
4. Research Agent applies its YAML rules and returns a completed task with a text artifact.
5. Writer applies its own YAML rules and returns the final completed task.

This sample has no authentication, durable task store, streaming, cancellation, or production-grade trust validation. Do not expose it publicly without adding those controls.
