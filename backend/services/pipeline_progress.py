"""
Tiny thread-safe in-memory broker for pipeline progress events.

The synchronous /api/upload/auto handler runs in FastAPI's threadpool while an
async SSE endpoint (/api/pipeline/{id}/progress) polls this dict and streams
events to the browser. No external dependencies (Redis/queue) required for the MVP.
"""
import threading
import time
from typing import Dict, Any, List

_lock = threading.Lock()
_progress: Dict[int, Dict[str, Any]] = {}

# Stage order + bracket percentages used by the pipeline
STAGES: List[str] = ["extract", "validate", "map", "generate"]
STAGE_BRACKETS = {  # (start_pct, end_pct)
    "extract":  (5,  35),
    "validate": (35, 55),
    "map":      (55, 80),
    "generate": (80, 100),
}


def reset(period_id: int) -> None:
    with _lock:
        _progress[period_id] = {
            "period_id": period_id,
            "stage": None,
            "stage_index": -1,
            "pct": 0,
            "log": [],
            "status": "running",
            "started_at": time.time(),
            "updated_at": time.time(),
            "result": None,
        }


def update(
    period_id: int,
    stage: str = None,
    pct: float = None,
    message: str = None,
    status: str = None,
    result: dict = None,
) -> Dict[str, Any]:
    with _lock:
        p = _progress.setdefault(period_id, {
            "period_id": period_id, "stage": None, "stage_index": -1,
            "pct": 0, "log": [], "status": "running",
            "started_at": time.time(), "updated_at": time.time(), "result": None,
        })
        if stage and stage != p.get("stage"):
            p["stage"] = stage
            p["stage_index"] = STAGES.index(stage) if stage in STAGES else p["stage_index"]
        if pct is not None:
            p["pct"] = max(p["pct"], float(pct))
        if message:
            p["log"].append({"ts": time.time(), "msg": message})
            # Keep the log bounded so a long-running pipeline doesn't grow unbounded
            if len(p["log"]) > 200:
                p["log"] = p["log"][-200:]
        if status:
            p["status"] = status
        if result is not None:
            p["result"] = result
        p["updated_at"] = time.time()
        return dict(p)


def snapshot(period_id: int) -> Dict[str, Any]:
    with _lock:
        snap = _progress.get(period_id)
        if not snap:
            return {
                "period_id": period_id, "stage": None, "stage_index": -1,
                "pct": 0, "log": [], "status": "idle",
                "started_at": 0, "updated_at": 0, "result": None,
            }
        # Return a copy with log truncated to last 50 entries to keep SSE payload small
        out = dict(snap)
        out["log"] = list(snap.get("log", []))[-50:]
        return out


def clear(period_id: int) -> None:
    with _lock:
        _progress.pop(period_id, None)
