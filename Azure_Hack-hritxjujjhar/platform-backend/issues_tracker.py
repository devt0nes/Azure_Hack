"""
issues_tracker.py - Centralized issue tracking for multi-agent system

Tracks:
- Open issues blocking agents
- Which agent reported the issue
- Which agent should resolve it
- Resolution status
"""

import json
import os
from datetime import datetime
from typing import List, Dict, Optional
import threading

ISSUES_FILE = "./workspace/issues.json"

class IssuesTracker:
    """Centralized issue tracking"""
    
    def __init__(self, file_path=ISSUES_FILE):
        self.file_path = file_path
        self.lock = threading.Lock()
        self._ensure_file()
    
    def _ensure_file(self):
        """Create issues file if it doesn't exist"""
        os.makedirs(os.path.dirname(self.file_path) or ".", exist_ok=True)
        if not os.path.exists(self.file_path):
            with open(self.file_path, "w") as f:
                json.dump({"issues": [], "resolved": []}, f, indent=2)
    
    def report_issue(self, 
                     component: str, 
                     description: str,
                     severity: str,
                     reported_by: str,
                     assigned_to: str,
                     tried: str = "",
                     context: Dict = None) -> Dict:
        """
        Report an issue blocking progress.
        
        Args:
            component: What is broken (e.g., "database schema")
            description: What went wrong
            severity: CRITICAL, HIGH, MEDIUM, LOW
            reported_by: Which agent reported this
            assigned_to: Which agent should fix it
            tried: What the agent tried
            context: Additional context data
        
        Returns:
            Issue object with ID and timestamp
        """
        with self.lock:
            with open(self.file_path, "r") as f:
                data = json.load(f)
            
            issue_id = len(data["issues"]) + len(data["resolved"]) + 1
            issue = {
                "id": issue_id,
                "component": component,
                "description": description,
                "severity": severity,
                "reported_by": reported_by,
                "assigned_to": assigned_to,
                "tried": tried,
                "context": context or {},
                "timestamp": datetime.now().isoformat(),
                "resolved": False,
                "resolved_at": None,
                "resolution": None
            }
            
            data["issues"].append(issue)
            
            with open(self.file_path, "w") as f:
                json.dump(data, f, indent=2)
            
            return issue
    
    def get_open_issues(self, 
                        severity_filter: Optional[str] = None,
                        assigned_to: Optional[str] = None) -> List[Dict]:
        """
        Get open issues.
        
        Args:
            severity_filter: Filter by severity (CRITICAL, HIGH, etc.) or None for all
            assigned_to: Filter by assigned agent or None for all
        
        Returns:
            List of open issues
        """
        with self.lock:
            with open(self.file_path, "r") as f:
                data = json.load(f)
        
        issues = data.get("issues", [])
        
        if severity_filter:
            issues = [i for i in issues if i["severity"] == severity_filter]
        
        if assigned_to:
            issues = [i for i in issues if i["assigned_to"] == assigned_to]
        
        return issues
    
    def get_blocking_issues(self, agent_role: str) -> List[Dict]:
        """Get issues that are blocking a specific agent"""
        with self.lock:
            with open(self.file_path, "r") as f:
                data = json.load(f)
        
        # Issues reported BY this agent are blocking them until resolved
        blocking = [i for i in data.get("issues", []) if i["reported_by"] == agent_role]
        return blocking
    
    def resolve_issue(self, issue_id: int, resolution: str) -> Dict:
        """
        Mark an issue as resolved.
        
        Args:
            issue_id: ID of issue to resolve
            resolution: How it was resolved
        
        Returns:
            Resolved issue object
        """
        with self.lock:
            with open(self.file_path, "r") as f:
                data = json.load(f)
            
            # Find and mark as resolved
            issue = None
            for i in data["issues"]:
                if i["id"] == issue_id:
                    issue = i
                    issue["resolved"] = True
                    issue["resolved_at"] = datetime.now().isoformat()
                    issue["resolution"] = resolution
                    data["resolved"].append(issue)
                    data["issues"].remove(i)
                    break
            
            with open(self.file_path, "w") as f:
                json.dump(data, f, indent=2)
            
            return issue
    
    def clear(self):
        """Clear all issues"""
        with self.lock:
            with open(self.file_path, "w") as f:
                json.dump({"issues": [], "resolved": []}, f, indent=2)
    
    def print_issues(self):
        """Print all open issues"""
        issues = self.get_open_issues()
        if not issues:
            return "✅ No open issues"
        
        output = "📋 Open Issues:\n"
        for issue in issues:
            output += f"\n[{issue['id']}] {issue['severity']} - {issue['component']}\n"
            output += f"    Reported by: {issue['reported_by']}\n"
            output += f"    Assigned to: {issue['assigned_to']}\n"
            output += f"    {issue['description']}\n"
            if issue['tried']:
                output += f"    Tried: {issue['tried']}\n"
        
        return output


# Global instance
_issues_tracker = None

def get_issues_tracker() -> IssuesTracker:
    """Get or create global issues tracker"""
    global _issues_tracker
    if _issues_tracker is None:
        _issues_tracker = IssuesTracker()
    return _issues_tracker

def set_issues_tracker(tracker: IssuesTracker):
    """Set global issues tracker"""
    global _issues_tracker
    _issues_tracker = tracker
