"""
Trace Manager - Records the complete system generation process to trace.json.
Each entry represents an executed node with its label, inputs, outputs, and status.
"""

import os
import json
from datetime import datetime
from typing import List, Dict, Any, Optional


def append_trace_entry(project_dir: str, entry: Dict[str, Any]) -> None:
    """
    Append a single trace entry to trace.json.
    Creates the file if it doesn't exist.

    Entry format:
    {
        "timestamp": "2026-07-02T12:00:00",
        "step": "D1",
        "type": "D",
        "label": "process sales data",
        "input": "d1.sales_raw",
        "output": "D1.csv (3 cols)",
        "status": "success",          # success | error | recovered
        "is_retry": false,            # true if this is a retry after error recovery
        "previous_error": null,       # if is_retry, the error summary from previous attempt
        "details": {}                 # optional extra info
    }
    """
    if not project_dir:
        return

    trace_path = os.path.join(project_dir, "trace.json")
    entries: List[Dict] = []

    if os.path.isfile(trace_path):
        try:
            with open(trace_path, "r", encoding="utf-8") as f:
                entries = json.load(f)
                if not isinstance(entries, list):
                    entries = []
        except (json.JSONDecodeError, Exception):
            entries = []

    entries.append(entry)

    try:
        with open(trace_path, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def make_trace_entry(
    step: str,
    node_type: str,
    label: str,
    input_desc: str,
    output_desc: str,
    status: str = "success",
    is_retry: bool = False,
    previous_error: Optional[str] = None,
    details: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Build a trace entry dict.
    """
    return {
        "timestamp": datetime.now().isoformat(),
        "step": step,
        "type": node_type,
        "label": label,
        "input": input_desc or "",
        "output": output_desc or "",
        "status": status,
        "is_retry": is_retry,
        "previous_error": previous_error,
        "details": details or {}
    }
