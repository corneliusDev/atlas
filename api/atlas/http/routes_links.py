"""Link feedback (SL-3): PUT /api/links/{a}/{b}/feedback -> LinkFeedbackRepository.record.

The only write the API makes besides enqueue (PRD Output 4). PUT on the ordered pair is
idempotent; the verdict replaces any earlier one for the pair.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from atlas.http.dto import FeedbackRequest, FeedbackResponse
from atlas.http.routes_common import ERR, VaultParam, get_document_reader, get_feedback_repo, need, parse_pair
from atlas.ports import LinkFeedbackRepository
from atlas.read.protocols import DocumentReader
from atlas.types import DEFAULT_VAULT_ID, VaultId

router = APIRouter()


@router.put("/api/links/{a}/{b}/feedback", response_model=FeedbackResponse, responses=ERR, tags=["links"])
def link_feedback(
    a: UUID,
    b: UUID,
    body: FeedbackRequest,
    repo: Annotated[LinkFeedbackRepository | None, Depends(get_feedback_repo)],
    documents: Annotated[DocumentReader | None, Depends(get_document_reader)],
    vault: VaultParam = DEFAULT_VAULT_ID,
) -> FeedbackResponse:
    pair = parse_pair(a, b)
    r = need(repo, "link feedback")
    vid = VaultId(vault)
    if documents is not None and not (documents.exists(vid, pair.a) and documents.exists(vid, pair.b)):
        raise HTTPException(status_code=404, detail="document not found")
    r.record(vid, pair, body.verdict)
    return FeedbackResponse(pair=pair, verdict=body.verdict, updated_at=datetime.now(UTC))
