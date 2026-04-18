"""
NavGuard AI Coding Agent — Backend
====================================
Single file. Run with:
    pip install fastapi uvicorn openai httpx supabase python-dotenv
    uvicorn main:app --reload --port 8000

What it does per request:
  1. Receive: prompt + PAT + repo + branch + skill_md text + session_id
  2. Fetch repo files from GitHub (read-only, via PAT)
  3. Pull last 10 messages from Supabase for this session
  4. Merge everything into one system prompt
  5. Stream LLM response back to frontend
  6. Save user message + assistant reply to Supabase
"""

import os, json, base64
from pathlib import Path
from typing import AsyncGenerator

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from openai import OpenAI
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
SUPABASE_URL   = os.getenv("SUPABASE_URL", "https://lfqcdeiwyguwsiolaaeu.supabase.co")
SUPABASE_KEY   = os.getenv("SUPABASE_KEY", "")
PRIMARY_MODEL  = os.getenv("PRIMARY_MODEL",  "minimax/minimax-text-01")
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL", "openai/gpt-4-turbo")

INCLUDE_EXT = {".ts",".tsx",".js",".jsx",".py",".sql",".json",".md",".yaml",".yml",".prisma",".sh",".env.example"}
SKIP_DIRS   = {"node_modules","dist",".git","__pycache__",".next","build","coverage",".turbo"}
MAX_FILE_CHARS  = 8_000
MAX_TOTAL_CHARS = 90_000

# ── Clients ───────────────────────────────────────────────────
llm      = OpenAI(api_key=OPENROUTER_KEY, base_url="https://openrouter.ai/api/v1")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI(title="NavGuard Agent")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── System prompt ─────────────────────────────────────────────
SYSTEM_TEMPLATE = """\
You are an expert coding agent for the NavGuard drone compliance SaaS backend.
You have read-only access to the codebase — you CANNOT push or write files directly.
Your job is to generate code the developer will copy and use.

## HOW YOU MUST BEHAVE

### Think first, code second
Before writing any code, reason through the problem out loud:
- What is actually being asked?
- What parts of the codebase are relevant?
- Are there edge cases or gotchas?
- Is there anything ambiguous that needs clarification?

### Ask when uncertain
If the request is vague or could be interpreted multiple ways, ASK before writing code.
State what you understood, then ask your clarifying question(s). Keep questions short — one or two at most.

### Suggest improvements
After fulfilling a request, proactively suggest related improvements or tweaks:
- Performance improvements
- Missing error handling
- Security considerations
- Tests worth writing
- Refactoring opportunities
Label these clearly as "💡 Suggestions" so the developer can choose to act on them or not.

### Code output format
When writing code, always output the FULL file — no snippets, no placeholders.
Mark the filename on the first line as a comment:
```typescript
// FILE: backend/src/services/newService.ts
... full file content ...
```

### Conventions
Follow the exact patterns, naming, and import style you see in the codebase.
Never introduce dependencies not already in package.json unless you flag it explicitly.

---

## PROJECT SKILL DOC
{skill_md}

---

## REPOSITORY: {repo} (branch: {branch})
{codebase}
"""

# ── GitHub fetcher ────────────────────────────────────────────
async def fetch_repo(repo: str, branch: str, pat: str) -> str:
    headers = {
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        # Fetch recursive tree
        r = await client.get(
            f"https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1",
            headers=headers
        )
        if r.status_code == 401:
            raise HTTPException(401, "GitHub PAT is invalid or expired.")
        if r.status_code == 404:
            raise HTTPException(404, f"Repo '{repo}' or branch '{branch}' not found.")
        if r.status_code != 200:
            raise HTTPException(502, f"GitHub error {r.status_code}: {r.text[:200]}")

        tree = r.json().get("tree", [])
        parts = []
        total = 0

        for item in tree:
            if item["type"] != "blob":
                continue
            path: str = item["path"]

            # Skip unwanted dirs
            if any(skip in path.split("/") for skip in SKIP_DIRS):
                continue
            # Check extension
            ext = Path(path).suffix
            if ext not in INCLUDE_EXT and Path(path).name not in {".env.example"}:
                continue
            # Skip lock files
            if path.endswith(("package-lock.json","yarn.lock","pnpm-lock.yaml")):
                continue

            if total >= MAX_TOTAL_CHARS:
                parts.append(f"### FILE: {path}\n[omitted — context limit reached]\n")
                continue

            # Fetch file content
            cr = await client.get(
                f"https://api.github.com/repos/{repo}/contents/{path}?ref={branch}",
                headers=headers
            )
            if cr.status_code != 200:
                continue

            raw = base64.b64decode(cr.json().get("content","")).decode("utf-8", errors="ignore")
            if len(raw) > MAX_FILE_CHARS:
                raw = raw[:MAX_FILE_CHARS] + f"\n... [truncated at {MAX_FILE_CHARS} chars]"

            parts.append(f"### FILE: {path}\n```\n{raw}\n```")
            total += len(raw)

    return "\n\n".join(parts) if parts else "[No supported files found in repository]"


# ── Supabase helpers ──────────────────────────────────────────
def get_history(session_id: str) -> list[dict]:
    """Return last 10 messages for this session, oldest first."""
    res = (
        supabase.table("agent_messages")
        .select("role,content")
        .eq("session_id", session_id)
        .order("created_at", desc=True)
        .limit(10)
        .execute()
    )
    return list(reversed(res.data or []))


def save_messages(session_id: str, user_msg: str, assistant_msg: str):
    supabase.table("agent_messages").insert([
        {"session_id": session_id, "role": "user",      "content": user_msg},
        {"session_id": session_id, "role": "assistant",  "content": assistant_msg},
    ]).execute()


# ── Request model ─────────────────────────────────────────────
class ChatRequest(BaseModel):
    prompt:     str
    session_id: str
    pat:        str          # GitHub Personal Access Token
    repo:       str          # owner/repo
    branch:     str = "main"
    skill_md:   str = ""     # content of the uploaded SKILL.md


# ── Main endpoint ─────────────────────────────────────────────
@app.post("/chat")
async def chat(req: ChatRequest):
    if not req.prompt.strip():
        raise HTTPException(400, "Prompt cannot be empty.")
    if not req.pat.strip():
        raise HTTPException(400, "GitHub PAT is required.")
    if "/" not in req.repo:
        raise HTTPException(400, "Repo must be in 'owner/repo' format.")

    # 1. Fetch repo
    try:
        codebase = await fetch_repo(req.repo.strip(), req.branch.strip(), req.pat.strip())
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Failed to fetch repo: {e}")

    # 2. Pull last 10 messages
    history = get_history(req.session_id)

    # 3. Build system prompt
    system = SYSTEM_TEMPLATE.format(
        skill_md=req.skill_md.strip() or "[No SKILL.md provided — working from codebase alone]",
        repo=req.repo,
        branch=req.branch,
        codebase=codebase,
    )

    # 4. Build messages list: history + new user message
    messages = [{"role": "system", "content": system}]
    for m in history:
        messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": req.prompt})

    # 5. Stream response, collect full reply for saving
    full_reply: list[str] = []

    async def stream() -> AsyncGenerator[str, None]:
        for attempt, model in enumerate([PRIMARY_MODEL, FALLBACK_MODEL]):
            try:
                if attempt == 1:
                    # Let the frontend know we switched
                    yield f"data: {json.dumps({'text': f'\\n\\n⚠️ Primary model unavailable, switching to fallback ({FALLBACK_MODEL})...\\n\\n'})}\n\n"

                response = llm.chat.completions.create(
                    model=model,
                    max_tokens=4096,
                    stream=True,
                    messages=messages,
                )
                for chunk in response:
                    delta = chunk.choices[0].delta.content or ""
                    if delta:
                        full_reply.append(delta)
                        yield f"data: {json.dumps({'text': delta})}\n\n"

                # Save to Supabase after streaming completes
                save_messages(req.session_id, req.prompt, "".join(full_reply))
                yield "data: [DONE]\n\n"
                return  # success — don't try fallback

            except Exception as e:
                if attempt == 0:
                    # Primary failed — clear any partial reply and try fallback
                    full_reply.clear()
                    continue
                # Both failed
                yield f"data: {json.dumps({'error': f'Both models failed. Last error: {str(e)}'})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/history/{session_id}")
def history(session_id: str):
    return get_history(session_id)


@app.delete("/history/{session_id}")
def clear_history(session_id: str):
    supabase.table("agent_messages").delete().eq("session_id", session_id).execute()
    return {"cleared": True}


@app.get("/health")
def health():
    return {"status": "ok", "primary_model": PRIMARY_MODEL, "fallback_model": FALLBACK_MODEL}
