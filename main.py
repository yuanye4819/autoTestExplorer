"""AI-Driven Web Exploration & Automated Testing System — FastAPI Entry Point."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from logging_config import setup_logging

# Initialize logging first
setup_logging()

from state import ws_connections, agent, test_runner
from routes.tasks import router as tasks_router
from routes.ws import router as ws_router


# ---- App ----
app = FastAPI(
    title="AI Web Exploration Testing System",
    description="AI-driven web exploration & automated test generation platform",
    version="1.1.0",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

# Include routers
app.include_router(tasks_router)
app.include_router(ws_router)


# ---- Startup ----
@app.on_event("startup")
async def startup():
    async def broadcast_ws(message: dict):
        task_id = message.get("task_id", "")
        if task_id in ws_connections:
            dead = []
            for ws in ws_connections[task_id]:
                try:
                    await ws.send_json(message)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                ws_connections[task_id].remove(ws)

    await agent.add_ws_callback(broadcast_ws)
    async def test_output(text: str):
        pass
    test_runner.on_output(test_output)


# ---- Static files ----
static_dir = Path(__file__).parent / "static"

@app.get("/")
async def serve_index():
    return FileResponse(static_dir / "index.html")

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# ---- Entry ----
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=True)
