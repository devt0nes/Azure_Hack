"""
Director Agent.
Receives a ReviewResult + file cache, routes each issue by severity,
collects patches, assembles the FinalReport.
"""
from __future__ import annotations
from models import ReviewResult, FilePatch, FinalReport, Severity
import fixer


def dispatch(review: ReviewResult, file_cache: dict[str, str]) -> FinalReport:
    low_issues  = [i for i in review.issues if i.severity == Severity.LOW]
    high_issues = [i for i in review.issues if i.severity == Severity.HIGH]

    print(f"[Director] {len(low_issues)} LOW  → GPT-4o-mini")
    print(f"[Director] {len(high_issues)} HIGH → GPT-4o")

    patches: list[FilePatch] = []

    for issue in low_issues:
        try:
            patches.append(fixer.fix(
                issue,
                use_mini=True,
                full_file_content=file_cache.get(issue.file_path, ""),
            ))
        except Exception as e:
            print(f"[Director] LOW fix failed {issue.issue_id}: {e}")

    for issue in high_issues:
        try:
            patches.append(fixer.fix(
                issue,
                use_mini=False,
                full_file_content=file_cache.get(issue.file_path, ""),
            ))
        except Exception as e:
            print(f"[Director] HIGH fix failed {issue.issue_id}: {e}")

    combined_diff = "\n".join(p.diff for p in patches if p.diff.strip())

    return FinalReport(
        pr_url=review.pr_url,
        repo=review.repo,
        total_issues=len(review.issues),
        low_severity=len(low_issues),
        high_severity=len(high_issues),
        patches=patches,
        combined_diff=combined_diff,
    )