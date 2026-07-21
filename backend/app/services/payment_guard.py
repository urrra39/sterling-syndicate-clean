from __future__ import annotations

"""Payment authorization kill switch — absolute blocker until human verifies funds.

While a contract is in `pending_payment_verification` and `is_payment_verified`
is False, Writer/Negotiator/delivery endpoints MUST refuse to run.
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.lead import Lead, PipelineStatus
from app.models.proposal import Contract
from app.services.notify import notify_payment_action_required

PAYMENT_LOCK_DETAIL = (
    "PAYMENT KILL SWITCH ACTIVE: this lead is pending_payment_verification. "
    "No agent drafts, negotiation replies, or deliverable work until you click "
    "Confirm Payment Received in the dashboard."
)


def get_contract_for_lead(db: Session, lead_id: UUID) -> Optional[Contract]:
    return db.scalar(select(Contract).where(Contract.lead_id == lead_id))


def is_payment_locked(db: Session, lead_id: UUID) -> bool:
    """True when autonomous work must freeze for this lead."""
    contract = get_contract_for_lead(db, lead_id)
    if contract is None:
        return False
    if contract.is_payment_verified:
        return False
    # Lock whenever verification is outstanding (status or flag)
    if contract.status == "pending_payment_verification":
        return True
    # Also lock active contracts that were never verified (fail-closed)
    return not contract.is_payment_verified


def assert_payment_cleared(db: Session, lead_id: UUID) -> None:
    """Raise 423 Locked if the kill switch is engaged. Cannot be bypassed by agents."""
    if is_payment_locked(db, lead_id):
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=PAYMENT_LOCK_DETAIL,
        )
    # Phase 6: also freeze agent spend while waiting on budget extension
    contract = get_contract_for_lead(db, lead_id)
    if contract is not None and contract.status == "paused_for_budget_extension":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                "PROFIT GUARD PAUSE: authorize a budget extension or review the draft "
                "before any further agent API spend."
            ),
        )


def lock_for_payment_verification(
    db: Session,
    *,
    lead: Lead,
    contract: Contract,
    client_name: str = "Client",
    amount: Optional[float] = None,
    send_alert: bool = True,
) -> Contract:
    """Freeze the lead and optionally fire a high-priority payment alert."""
    contract.status = "pending_payment_verification"
    contract.is_payment_verified = False
    contract.payment_claimed_at = datetime.now(timezone.utc)
    if client_name:
        contract.client_display_name = client_name.strip()[:200]
    lead.pipeline_status = PipelineStatus.PENDING_PAYMENT_VERIFICATION.value
    if send_alert:
        notify_payment_action_required(
            client_name=contract.client_display_name or client_name or "Client",
            amount=amount if amount is not None else contract.agreed_price,
            currency=contract.currency,
            lead_id=str(lead.id),
            lead_title=lead.title,
        )
    return contract


def confirm_payment_received(
    db: Session,
    *,
    lead: Lead,
    contract: Contract,
) -> Contract:
    """Human-only unlock. Agents cannot call this path."""
    from app.services.profit_guard import init_budget

    contract.is_payment_verified = True
    contract.payment_verified_at = datetime.now(timezone.utc)
    if contract.status == "pending_payment_verification":
        contract.status = "active"
    if lead.pipeline_status == PipelineStatus.PENDING_PAYMENT_VERIFICATION.value:
        lead.pipeline_status = PipelineStatus.IN_PROGRESS.value
    init_budget(contract)
    return contract
