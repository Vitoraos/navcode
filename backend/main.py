import os
import json
import base64
import asyncio
from pathlib import Path
from typing import AsyncGenerator, List, Optional

import httpx
import uvicorn
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
MAX_TOTAL_CHARS = 50000

SKIP_DIRS = {".git", "node_modules", "__pycache__"}
INCLUDE_EXT = {".ts", ".tsx", ".js", ".jsx", ".py", ".json", ".md"}

# ── Clients ───────────────────────────────────────────────────
llm = OpenAI(
    api_key=OPENROUTER_KEY,
    base_url="https://openrouter.ai/api/v1"
)

# ✅ Safe Supabase init
supabase: Optional[Client] = None

try:
    if SUPABASE_URL and SUPABASE_KEY:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("Supabase connected")
    else:
        print("Supabase env missing")
except Exception as e:
    print("Supabase init failed:", e)

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
    selected_files: Optional[List[str]] = []

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

# ── GitHub helpers ────────────────────────────────────────────
async def fetch_single_file(client, headers, repo, branch, path):
    cr = await client.get(
        f"https://api.github.com/repos/{repo}/contents/{path}?ref={branch}",
        headers=headers
    )
    if cr.status_code != 200:
        return None
    content = cr.json().get("content", "")
    if not content:
        return None
    return base64.b64decode(content).decode("utf-8", errors="ignore")

async def fetch_selected_files(repo, branch, pat, selected_files):
    headers = {
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github+json",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        parts = []
        total = 0

        for path in selected_files:
            raw = await fetch_single_file(client, headers, repo, branch, path)
            if not raw:
                continue

            if len(raw) > MAX_FILE_CHARS:
                raw = raw[:MAX_FILE_CHARS] + "\n... [truncated]"

            if total + len(raw) > MAX_TOTAL_CHARS:
                break

            parts.append(f"### FILE: {path}\n```\n{raw}\n```")
            total += len(raw)

        return "\n".join(parts) if parts else "[No files fetched]"

# ── Supabase memory ───────────────────────────────────────────
def get_history(session_id: str):
    if not supabase:
        return []

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
    if not supabase:
        return

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

    codebase = await fetch_selected_files(
        req.repo,
        req.branch,
        req.pat,
        req.selected_files
    )

    history = get_history(req.session_id)

    system = SYSTEM_TEMPLATE.format(
        skill_md=req.skill_md or "[No SKILL.md provided]",
        codebase=codebase
    )

    messages = [{"role": "system", "content": system}]
    messages += history
    messages.append({"role": "user", "content": req.prompt})

    full_reply = []

    async def stream() -> AsyncGenerator[str, None]:
        import traceback # 🔥 Added for deep debugging
        
        for attempt, model in enumerate([PRIMARY_MODEL, FALLBACK_MODEL]):
            try:
                print(f"🔄 Attempting OpenRouter call with model: {model}")
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
                print(f"✅ Successfully completed stream with {model}")
                return

            except Exception as e:
                print(f"❌ ERROR on attempt {attempt+1} ({model}):")
                print(e) 
                
                if attempt == 0:
                    print("⚠️ Falling back to secondary model...")
                    full_reply.clear()
                    continue

                # Dump the deep traceback to your mobile terminal so you know EXACTLY what is crashing
                print("\n🚨 CRITICAL OPENROUTER FAILURE TRACEBACK 🚨")
                traceback.print_exc()
                
                # Send the error to the React frontend
                error_msg = str(e).replace('"', "'") # Escape quotes so JSON dumping doesn't break
                yield f"data: {json.dumps({'error': f'OpenRouter Failed: {error_msg}'})}\n\n"

# ── Utilities ────────────────────────────────────────────────
@app.get("/history/{session_id}")
def history(session_id: str):
    return get_history(session_id)

@app.delete("/history/{session_id}")
def clear_history(session_id: str):
    if not supabase:
        return {"cleared": False}

    supabase.table("agent_messages").delete().eq("session_id", session_id).execute()
    return {"cleared": True}

@app.get("/health")
def health():
    return {
        "status": "ok",
        "primary_model": PRIMARY_MODEL,
        "fallback_model": FALLBACK_MODEL
    }

# ── Run ───────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 10000))
    )
