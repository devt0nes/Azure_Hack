from __future__ import annotations
from enum import Enum
from pydantic import BaseModel, Field
import uuid


class Severity(str, Enum):
    LOW  = "LOW"   # style, minor bugs → GPT-4o-mini
    HIGH = "HIGH"  # logic, security   → GPT-4o


class Issue(BaseModel):
    issue_id:     str = Field(default_factory=lambda: str(uuid.uuid4()))
    file_path:    str
    line_start:   int
    line_end:     int
    severity:     Severity
    category:     str        # "security" | "logic" | "bug" | "style"
    description:  str
    code_snippet: str


class ReviewResult(BaseModel):
    pr_url:               str
    repo:                 str
    issues:               list[Issue]
    total_files_reviewed: int


class FilePatch(BaseModel):
    file_path:   str
    issue_id:    str
    severity:    Severity
    model_used:  str
    diff:        str
    explanation: str


class FinalReport(BaseModel):
    pr_url:        str
    repo:          str
    total_issues:  int
    low_severity:  int
    high_severity: int
    patches:       list[FilePatch]
    combined_diff: str   # all diffs joined — pipe straight into `git apply`