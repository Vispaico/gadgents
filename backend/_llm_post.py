"""Out-of-process HTTP POST for backend.llm.

A stalled OpenRouter recv on macOS is NOT interruptible by httpx's read timeout,
a socket timeout, closing the client, or signal.alarm (all fail — the call blocks
forever and keeps billing). The ONLY reliable kill is terminating the OS process
(SIGKILL can't be ignored by a blocked recv).

So each LLM POST runs in a SEPARATE subprocess via `sys.executable -m
backend._llm_post_child` (the SAME mechanism backend.editorial_worker uses, which
works on macOS). The child prints a JSON result line to stdout; the parent reads
it with a wall-clock deadline and SIGKILLs the child on a stall. If the child
doesn't answer in `timeout_s`, the parent raises so the caller's retry/fallback
path engages instead of wedging the (editorial) worker.

We use `subprocess` + `-m` (NOT multiprocessing): multiprocessing.spawn re-imports
__main__ and crashes on a stdin/worker parent, and multiprocessing.fork segfaults
(httpx + Obj-C runtime) on the actual httpx call. `subprocess -m` is the one
approach that reliably runs the child on macOS.
"""

import json
import subprocess
import sys


def timed_post(url: str, headers: dict, payload: dict, timeout_s: int = 120):
    """POST as JSON in a child process; return (data_dict, status_code).

    Raises RuntimeError if the child times out (stall) or errors. Bounded by
    `timeout_s` regardless of what OpenRouter does.
    """
    inp = json.dumps({"url": url, "headers": headers, "json": payload})
    proc = subprocess.Popen(
        [sys.executable, "-m", "backend._llm_post_child"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        out, err = proc.communicate(input=inp, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        # Stall: kill the OS process holding the stuck recv. Unblockable.
        proc.kill()
        try:
            proc.wait(timeout=2)
        except Exception:
            pass
        raise RuntimeError(
            f"LLM HTTP call timed out (provider stalled) after {timeout_s}s"
        )
    if proc.returncode != 0:
        raise RuntimeError(
            f"LLM HTTP call failed (child rc={proc.returncode}): {(err or '')[:200]}"
        )
    try:
        msg = json.loads(out.strip().splitlines()[-1])
    except Exception:
        raise RuntimeError(f"LLM HTTP call returned unparsable output: {(out or '')[:200]}")
    if msg.get("ok"):
        return msg.get("data"), msg.get("status", 0)
    raise RuntimeError(f"LLM HTTP call failed: {msg.get('error', 'unknown')}")
