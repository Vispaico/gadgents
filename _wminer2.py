import time, signal
from backend.llm import LLMClient
from backend.router import route
from backend.editorial import _stage_system_prompt
from backend.db import get_session, BrandProfile
from sqlmodel import select

def h(s,f): raise TimeoutError("hard 90s")
signal.signal(signal.SIGALRM, h)

essay="Why most AI writing tools fail at brand voice. They summarize instead of multiplying value. A calm, founder-to-founder take on what actually earns trust."
with next(get_session()) as s:
    brand=s.exec(select(BrandProfile).where(BrandProfile.name=="Vispaico")).first()
sys_prompt=_stage_system_prompt(s, "idea_miner")
msgs=[{"role":"system","content":sys_prompt},{"role":"user","content":f'SOURCE ESSAY:\n"""\n{essay}\n"""\n\nReturn only 12-15 ideas as JSON.'}]
llm=LLMClient()
for mt in [3000, 2000]:
    print(f"miner route() mixed or-qwen37 max_tokens={mt}, alarm(90)", flush=True)
    t0=time.time(); signal.alarm(90)
    try:
        text, model = route(llm, messages=msgs, model_id="or-qwen37", goal="mixed", fusion=False, max_tokens=mt)
        print(f"  OK @ {round(time.time()-t0,1)}s len {len(text)}", flush=True)
    except Exception as e:
        print(f"  EXC @ {round(time.time()-t0,1)}s: {type(e).__name__} {str(e)[:90]}", flush=True)
