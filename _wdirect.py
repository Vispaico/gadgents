import time, signal, json, sys
from backend.db import get_session, get_or_create_dev_user, EditorialRun, BrandProfile
from sqlmodel import select
from backend.editorial_worker import run_worker

def h(s,f): raise TimeoutError("TEST 150s")
signal.signal(signal.SIGALRM, h); signal.alarm(150)

with next(get_session()) as s:
    user = get_or_create_dev_user(s)
    brand = s.exec(select(BrandProfile).where(BrandProfile.name == "Vispaico")).first()
    bid, uid = brand.id, user.id
    run = EditorialRun(user_id=uid, brand_id=bid, essay_text="Why most AI writing tools fail at brand voice. They summarize instead of multiplying value.", status="running")
    s.add(run); s.commit(); s.refresh(run); rid = run.id
print(f"DIRECT worker for run {rid}, calling run_worker in MAIN thread (same as subprocess -m)", flush=True)
print("alarm(150) armed; will raise if stalled >150s", flush=True)
t0=time.time()
try:
    run_worker(rid, "Why most AI writing tools fail at brand voice. They summarize instead of multiplying value.", bid, ["linkedin"], "mixed", 2, False, uid)
    print("run_worker RETURNED @", round(time.time()-t0,1), flush=True)
except TimeoutError as e:
    print("STALLED -> SIGALRM fired:", e, "@", round(time.time()-t0,1), flush=True)
except Exception as e:
    print("EXC:", type(e).__name__, str(e)[:200], "@", round(time.time()-t0,1), flush=True)
