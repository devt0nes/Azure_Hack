"""
FastAPI entrypoint.

POST /review  { "pr_url": "https://github.com/owner/repo/pull/42" }
"""
from __future__ import annotations
from dotenv import load_dotenv
load_dotenv()   # must be before any other local imports

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from models import FinalReport
from code_review_agent import review_pr
from director_agent import dispatch

app = FastAPI(title="Code Review Agent — MVP", version="0.1.0")


class ReviewRequest(BaseModel):
    pr_url: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/review", response_model=FinalReport)
def review(req: ReviewRequest) -> FinalReport:
    try:
        review_result, file_cache = review_pr(req.pr_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"GitHub fetch failed: {e}")

    if not review_result.issues:
        return FinalReport(
            pr_url=req.pr_url,
            repo=review_result.repo,
            total_issues=0,
            low_severity=0,
            high_severity=0,
            patches=[],
            combined_diff="",
        )

    return dispatch(review_result, file_cache)