#!/usr/bin/env python3
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from typing import Literal, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel

from fdt_langgraph.graph import build_debate_graph_no_checkpoint
from fdt_langgraph.state import create_initial_state

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fdt_api")

app = FastAPI(title="FDT Futures Debate Team API", version="1.0")

_running_tasks = {}


class DebateRequest(BaseModel):
    mode: Literal["default", "fast", "deep_research", "tournament"] = "default"
    trace_id: Optional[str] = None


class DebateResponse(BaseModel):
    trace_id: str
    status: str
    phase: str
    report_path: Optional[str] = None
    error: Optional[str] = None


def generate_trace_id() -> str:
    return f"fdt-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"


async def run_debate_async(trace_id: str, mode: str):
    try:
        initial_state = create_initial_state(trace_id, mode=mode)

        graph = build_debate_graph_no_checkpoint(mode=mode)
        config = {"configurable": {"thread_id": trace_id}}
        result = await graph.ainvoke(initial_state, config=config)

        _running_tasks[trace_id] = {
            "status": "completed",
            "phase": result.get("current_phase"),
            "report_path": result.get("report_path"),
            "error": result.get("error"),
        }
        logger.info(f"Debate {trace_id} completed")
    except Exception as e:
        _running_tasks[trace_id] = {
            "status": "failed",
            "phase": "error",
            "report_path": None,
            "error": str(e),
        }
        logger.error(f"Debate {trace_id} failed: {e}")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "fdt-api"}


@app.post("/api/v1/debate", response_model=DebateResponse)
async def trigger_debate(request: DebateRequest, background_tasks: BackgroundTasks):
    trace_id = request.trace_id or generate_trace_id()

    if trace_id in _running_tasks:
        raise HTTPException(status_code=400, detail=f"Task {trace_id} already exists")

    _running_tasks[trace_id] = {"status": "running", "phase": "P0", "report_path": None, "error": None}
    background_tasks.add_task(run_debate_async, trace_id, request.mode)

    return DebateResponse(trace_id=trace_id, status="running", phase="P0")


@app.get("/api/v1/debate/{trace_id}", response_model=DebateResponse)
async def get_debate_status(trace_id: str):
    if trace_id not in _running_tasks:
        raise HTTPException(status_code=404, detail=f"Task {trace_id} not found")

    task = _running_tasks[trace_id]
    return DebateResponse(
        trace_id=trace_id,
        status=task["status"],
        phase=task["phase"],
        report_path=task.get("report_path"),
        error=task.get("error"),
    )


@app.get("/api/v1/status")
async def get_status():
    running = sum(1 for t in _running_tasks.values() if t["status"] == "running")
    completed = sum(1 for t in _running_tasks.values() if t["status"] == "completed")
    failed = sum(1 for t in _running_tasks.values() if t["status"] == "failed")
    return {"running": running, "completed": completed, "failed": failed}


if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("FDT_API_HOST", "0.0.0.0")
    port = int(os.environ.get("FDT_API_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
