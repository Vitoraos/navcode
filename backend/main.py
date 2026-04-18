"""
NavGuard AI Coding Agent — Backend (File-Scoped Version)
========================================================
Now supports explicit file selection instead of full repo ingestion.

Flow:
  1. Receive prompt + PAT + repo + branch + skill_md + selected_files + session_id
  2. Fetch ONLY selected GitHub files
  3. Pull last 10 messages from Supabase
  4. Merge into system prompt
  5. Stream LLM response
  6. Save conversation to Supabase
"""

import os, json, base64
from pathlib import Path
from typing import AsyncGenerator, List
from typing import List, Optional
import asyncio

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
SUPABASE_URL   = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY   = os.getenv("SUPABASE_KEY", "")

PRIMARY_MODEL  = os.getenv("PRIMARY_MODEL", "minimax/minimax-text-01")
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL", "openai/gpt-4-turbo")

MAX_FILE_CHARS = 8000

# ── Clients ───────────────────────────────────────────────────
llm = OpenAI(
    api_key=OPENROUTER_KEY,
    base_url="https://openrouter.ai/api/v1"
)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI(title="NavGuard Agent (File Scoped)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Request Model ─────────────────────────────────────────────
class ChatRequest(BaseModel):
    prompt: str
    session_id: str
    pat: str
    repo: str
    branch: str = "main"
    skill_md: str = ""
    selected_files: Optional[List[str]] = [] # 🔥 Fix 422 mismatch

# ── System Prompt ─────────────────────────────────────────────
SYSTEM_TEMPLATE = """
You are an expert coding agent for NavGuard.

You ONLY see selected repository files.
Do not assume existence of any other files.

## RULES
- Reason before coding
- Ask if unclear
- Output full files only
- Follow existing patterns strictly

---

## SKILL DOC
{skill_md}

---

## REPOSITORY CONTEXT (SELECTED FILES ONLY)
{codebase}
"""


# ── GitHub file fetcher (selected only) ───────────────────────
async def fetch_single_file(client, headers, repo, branch, path):
    cr = await client.get(
        f"https://api.github.com/repos/{repo}/contents/{path}?ref={branch}",
        headers=headers
    )
    if cr.status_code != 200:
        return None
    content = cr.json().get("content", "")
    if not content: return None
    return base64.b64decode(content).decode("utf-8", errors="ignore")

async def fetch_repo(repo: str, branch: str, pat: str) -> str:
    headers = {
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            f"https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1",
            headers=headers
        )
        if r.status_code != 200:
            raise HTTPException(r.status_code, r.json().get("message", "GitHub API error"))
            
        tree = r.json().get("tree", [])
        valid_paths = []
        for item in tree:
            if item["type"] != "blob": continue
            path = item["path"]
            if any(skip in path.split("/") for skip in SKIP_DIRS): continue
            if Path(path).suffix not in INCLUDE_EXT and Path(path).name != ".env.example": continue
            if path.endswith(("package-lock.json","yarn.lock","pnpm-lock.yaml")): continue
            valid_paths.append(path)

        # Concurrency limiter (10 at a time)
        sem = asyncio.Semaphore(10)
        async def fetch_with_limit(p):
            async with sem:
                return await fetch_single_file(client, headers, repo, branch, p)
                
        tasks = [fetch_with_limit(p) for p in valid_paths[:50]] # Cap at 50 files to stay under context limit
        results = await asyncio.gather(*tasks)

        parts = []
        total = 0
        for path, raw in zip(valid_paths[:50], results):
            if raw is None: continue
            if len(raw) > MAX_FILE_CHARS:
                raw = raw[:MAX_FILE_CHARS] + f"\n... [truncated at {MAX_FILE_CHARS} chars]"
            if total + len(raw) > MAX_TOTAL_CHARS:
                parts.append(f"### FILE: {path}\n[omitted — context limit reached]\n")
                break
            parts.append(f"### FILE: {path}\n```\n{raw}\n```")
            total += len(raw)

        return "\n".join(parts) if parts else "[No supported files found]"


# ── Supabase memory ───────────────────────────────────────────
def get_history(session_id: str):
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
        {"session_id": session_id, "role": "user", "content": user_msg},
        {"session_id": session_id, "role": "assistant", "content": assistant_msg},
    ]).execute()


# ── Chat endpoint ─────────────────────────────────────────────
@app.post("/chat")
async def chat(req: ChatRequest):

    if not req.prompt.strip():
        raise HTTPException(400, "Prompt required")

    if not req.pat.strip():
        raise HTTPException(400, "GitHub PAT required")

    if "/" not in req.repo:
        raise HTTPException(400, "Repo must be owner/repo")

    if not req.selected_files:
        raise HTTPException(400, "No files selected")

    # 1. Fetch ONLY selected files
    codebase = await fetch_selected_files(
        req.repo,
        req.branch,
        req.pat,
        req.selected_files
    )

    # 2. Load history
    history = get_history(req.session_id)

    # 3. Build system prompt
    system = SYSTEM_TEMPLATE.format(
        skill_md=req.skill_md or "[No SKILL.md provided]",
        codebase=codebase
    )

    messages = [{"role": "system", "content": system}]

    for m in history:
        messages.append({"role": m["role"], "content": m["content"]})

    messages.append({"role": "user", "content": req.prompt})

    # 4. Stream response
    full_reply = []

    async def stream() -> AsyncGenerator[str, None]:
        for attempt, model in enumerate([PRIMARY_MODEL, FALLBACK_MODEL]):
            try:

                response = llm.chat.completions.create(
                    model=model,
                    messages=messages,
                    stream=True,
                    max_tokens=4096,
                )

                for chunk in response:
                    delta = chunk.choices[0].delta.content or ""
                    if delta:
                        full_reply.append(delta)
                        yield f"data: {json.dumps({'text': delta})}\n\n"

                save_messages(req.session_id, req.prompt, "".join(full_reply))
                yield "data: [DONE]\n\n"
                return

            except Exception as e:
                if attempt == 0:
                    full_reply.clear()
                    continue

                yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


# ── Utilities ────────────────────────────────────────────────
@app.get("/history/{session_id}")
def history(session_id: str):
    return get_history(session_id)


@app.delete("/history/{session_id}")
def clear_history(session_id: str):
    supabase.table("agent_messages").delete().eq("session_id", session_id).execute()
    return {"cleared": True}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "primary_model": PRIMARY_MODEL,
        "fallback_model": FALLBACK_MODEL
    }
