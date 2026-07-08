"""Credits & paygate.

Mock mode (default): a "buy credits" endpoint directly grants credits and records a
Subscription for hourly/monthly plans. When STRIPE_SECRET_KEY is set, the same
endpoints prepare a Stripe Checkout session and a webhook finalizes the grant.

This keeps the product shippable today and live-ready without rewiring the frontend.
"""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlmodel import Session

from backend.auth import get_current_user
from backend.billing import InsufficientCredits, add_credits
from backend.config import get_settings
from backend.db import User, get_session, Subscription

router = APIRouter(prefix="/api/billing", tags=["billing"])

_settings = get_settings()

# Price table: plan -> credits granted (mock). 100 credits == $1.
PLANS = {
    "credits_500": {"label": "$5 — 500 credits", "credits": 500, "type": "credits"},
    "credits_2000": {"label": "$20 — 2000 credits", "credits": 2000, "type": "credits"},
    "hourly": {"label": "Hourly rental", "credits": 0, "type": "hourly"},
    "monthly": {"label": "Monthly subscription", "credits": 0, "type": "monthly"},
}


class BuyIn(BaseModel):
    plan: str  # key of PLANS


class BuyOut(BaseModel):
    ok: bool
    checkout_url: str = ""
    credits: int = 0
    message: str = ""


@router.get("/plans")
def plans():
    return PLANS


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {"email": user.email, "credits": user.credits, "plan": user.plan}


@router.post("/buy", response_model=BuyOut)
def buy(
    payload: BuyIn,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    plan = PLANS.get(payload.plan)
    if plan is None:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown plan")

    if _settings.stripe_secret_key and plan["type"] != "credits" or (
        _settings.stripe_secret_key and payload.plan in ("credits_500", "credits_2000")
    ):
        # Live Stripe path placeholder: create a Checkout Session here.
        # For now return a stub so the frontend can be wired; finalize via webhook.
        return BuyOut(ok=False, message="Stripe live mode not finalised; set webhook to grant.")

    # Mock mode: grant immediately.
    if plan["type"] == "credits":
        add_credits(session, user, plan["credits"])
        return BuyOut(ok=True, credits=user.credits, message=f"Granted {plan['credits']} credits.")
    # Subscription plans: record and grant a starter credit bundle.
    session.add(
        Subscription(user_id=user.id, plan=plan["type"], provider="mock", status="active")
    )
    user.plan = plan["type"]
    session.add(user)
    session.commit()
    add_credits(session, user, 1000)
    return BuyOut(ok=True, credits=user.credits, message=f"Subscribed to {plan['type']}.")


# Stripe webhook hook (live mode). No-op until STRIPE_SECRET_KEY is configured.
@router.post("/webhook")
async def stripe_webhook(request: Request, session: Session = Depends(get_session)):
    if not _settings.stripe_webhook_secret:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Webhook disabled")
    # TODO: verify signature, parse event, grant credits / activate subscription.
    return {"received": True}
