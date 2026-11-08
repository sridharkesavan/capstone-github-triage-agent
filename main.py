"""
Phase 3: Cloud Run REST API for GitHub Issue Triage Agent

This file serves the agent as a web service on Google Cloud Run.
Users can hit HTTP endpoints to trigger triage and manage approvals.

Endpoints:
  POST /triage       — Classify issues
  GET  /approvals    — Get pending approvals
  POST /approve      — Approve an action
  POST /reject       — Reject an action
  POST /execute      — Execute approved actions
"""

import os
import json
import sys
from pathlib import Path
from typing import Optional
from flask import Flask, request, jsonify
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent))

from src.agent import GitHubTriageAgent
from src.hitl_gate import Action
from src.tracing import flush

# Initialize Flask app
app = Flask(__name__)

# Global agent instance
agent = None

# Store for pending approvals (in-memory for now, Phase 4 will use persistent storage)
pending_approvals = {}
execution_history = []


def init_agent():
    """Initialize the agent on first request."""
    global agent
    if agent is None:
        try:
            agent = GitHubTriageAgent(enable_hitl=True)
            print("[OK] Agent initialized")
        except Exception as e:
            print(f"[ERROR] Failed to initialize agent: {e}")
            return False
    return True


@app.before_request
def startup():
    """Initialize agent before handling requests."""
    if agent is None:
        if not init_agent():
            return jsonify({"error": "Failed to initialize agent"}), 500


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "agent_initialized": agent is not None,
        "pending_approvals": len(pending_approvals),
        "executions": len(execution_history)
    }), 200


@app.route('/triage', methods=['POST'])
def triage():
    """
    Classify issues in a GitHub repository.
    
    Request body:
    {
      "repo": "owner/repo",           (optional, uses .env default if not provided)
      "limit": 5                      (optional, default 5)
    }
    
    Returns:
    {
      "status": "success",
      "issues_found": 3,
      "pending_approvals": [
        {
          "id": "action_0",
          "issue_number": 3,
          "issue_title": "...",
          "classification": "bug",
          "labels": [...],
          "comment": "..."
        }
      ]
    }
    """
    try:
        data = request.get_json() or {}
        repo = data.get('repo')
        limit = data.get('limit', 5)
        
        # Override repo if provided
        if repo:
            agent.gh_tools.repo = agent.gh_tools.gh.get_repo(repo)
            print(f"[OK] Switched to repo: {repo}")
        
        # Process issues
        print(f"[TRIAGE] Fetching up to {limit} issues...")
        results = agent.process_issues(limit=limit, use_demo=False)
        
        if not results:
            return jsonify({
                "status": "success",
                "message": "No issues found",
                "issues_found": 0,
                "pending_approvals": []
            }), 200
        
        # Propose actions
        # Start from a clean slate: drop proposals left over from earlier runs
        pending_approvals.clear()
        agent.hitl_gate.clear_pending()

        for result in results:
            before = len(agent.hitl_gate.pending_actions)
            agent.propose_github_action(result)

            # The gate skips invalid results (e.g. a missing issue number)
            if len(agent.hitl_gate.pending_actions) == before:
                print(f"[SKIP] No action proposed for: {result.get('issue_title')}")
                continue

            # Use the Action's own id and values: what you approve is what gets written
            action = agent.hitl_gate.pending_actions[-1]
            pending_approvals[action.id] = {
                "issue_number": action.issue_number,
                "issue_title": action.issue_title,
                "classification": action.classification,
                "labels": action.labels,
                "comment": action.comment,
                "approved": False,
                "result": result
            }

        if results and not pending_approvals:
            print(f"[WARN] {len(results)} issue(s) classified but 0 proposed")
        failed = [r for r in results if r.get('fallback') is True]
        warnings = []
        if results and not pending_approvals:
            warnings.append(f"{len(results)} issue(s) classified but none proposed; check logs for [SKIP] lines")
        if failed:
            print(f"[WARN] {len(failed)} issue(s) could not be classified (parse or API error) and were not proposed")
            warnings.append(f"{len(failed)} issue(s) could not be classified (parse or API error) and were not proposed")
        flush()  # send buffered traces before Cloud Run can freeze the instance
        return jsonify({
            "status": "success",
            "issues_found": len(results),
            "proposed": len(pending_approvals),
            "classification_failures": len(failed),
            "warning": " ".join(warnings) or None,
            "pending_approvals": list(pending_approvals.keys()),
            "approvals": pending_approvals
        }), 200
    
    except Exception as e:
        print(f"[ERROR] Triage failed: {e}")
        return jsonify({"error": str(e)}), 400


@app.route('/approvals', methods=['GET'])
def get_approvals():
    """
    Get pending approvals awaiting user decision.
    
    Returns:
    {
      "pending": [
        {
          "id": "action_0",
          "issue_number": 3,
          "issue_title": "...",
          "classification": "bug",
          ...
        }
      ],
      "count": 1
    }
    """
    return jsonify({
        "pending": list(pending_approvals.keys()),
        "count": len(pending_approvals),
        "approvals": pending_approvals
    }), 200


@app.route('/approve', methods=['POST'])
def approve_action():
    """
    Approve a pending action.
    
    Request body:
    {
      "action_id": "action_0",
      "note": "Looks good"  (optional)
    }
    
    Returns:
    {
      "status": "approved",
      "action_id": "action_0",
      "issue_number": 3
    }
    """
    try:
        data = request.get_json() or {}
        action_id = data.get('action_id')
        note = data.get('note', '')
        
        if action_id not in pending_approvals:
            return jsonify({"error": f"Action {action_id} not found"}), 404
        
        approval = pending_approvals[action_id]
        
        # Approve in agent's gate
        if agent.hitl_gate.approve_by_id(action_id, note=note):
            approval['approved'] = True
            approval['approval_note'] = note
            
            return jsonify({
                "status": "approved",
                "action_id": action_id,
                "issue_number": approval['issue_number']
            }), 200
        else:
            return jsonify({"error": "Failed to approve action"}), 400
    
    except Exception as e:
        print(f"[ERROR] Approval failed: {e}")
        return jsonify({"error": str(e)}), 400


@app.route('/reject', methods=['POST'])
def reject_action():
    """
    Reject a pending action.
    
    Request body:
    {
      "action_id": "action_0",
      "reason": "Not appropriate"  (optional)
    }
    
    Returns:
    {
      "status": "rejected",
      "action_id": "action_0",
      "issue_number": 3
    }
    """
    try:
        data = request.get_json() or {}
        action_id = data.get('action_id')
        reason = data.get('reason', 'Rejected by user')
        
        if action_id not in pending_approvals:
            return jsonify({"error": f"Action {action_id} not found"}), 404
        
        approval = pending_approvals[action_id]
        
        # Reject in agent's gate
        if agent.hitl_gate.reject_by_id(action_id, reason=reason):
            del pending_approvals[action_id]
            
            return jsonify({
                "status": "rejected",
                "action_id": action_id,
                "issue_number": approval['issue_number'],
                "reason": reason
            }), 200
        else:
            return jsonify({"error": "Failed to reject action"}), 400
    
    except Exception as e:
        print(f"[ERROR] Rejection failed: {e}")
        return jsonify({"error": str(e)}), 400


@app.route('/execute', methods=['POST'])
def execute():
    """
    Execute all approved actions on GitHub.
    
    Returns:
    {
      "status": "executed",
      "approved_count": 1,
      "executed": [
        {
          "issue_number": 3,
          "actions": ["add_labels", "add_comment"]
        }
      ]
    }
    """
    try:
        if not agent or not agent.hitl_gate:
            return jsonify({"error": "HITL gate not initialized"}), 400
        
        # Log the decisions first, then take the approved actions out of the
        # gate so each approval can only be executed once
        agent.hitl_gate.save_approvals("approval_log.json")
        approved = agent.hitl_gate.pop_approved()
        
        if not approved:
            return jsonify({
                "status": "no_actions",
                "message": "No approved actions to execute"
            }), 200
        
        # Execute approved actions
        executed = []
        for action in approved:
            issue_num = action.issue_number
            actions_taken = []
            
            # Add labels
            if action.action_type in ['add_labels', 'both']:
                if agent.gh_tools.apply_labels(action):
                    actions_taken.append('add_labels')
            
            # Add comment
            if action.action_type in ['add_comment', 'both']:
                if action.comment and agent.gh_tools.post_comment(action):
                    actions_taken.append('add_comment')
            
            executed.append({
                "issue_number": issue_num,
                "actions": actions_taken
            })
        
        
        # Remove only the executed proposals; undecided ones stay pending
        for aid in [k for k, v in pending_approvals.items() if v.get('approved')]:
            del pending_approvals[aid]
        
        # Log execution
        execution_history.append({
            "count": len(executed),
            "timestamp": str(os.popen('date').read()).strip() if os.name != 'nt' else 'N/A'
        })
        
        return jsonify({
            "status": "executed",
            "approved_count": len(approved),
            "executed": executed
        }), 200
    
    except Exception as e:
        print(f"[ERROR] Execution failed: {e}")
        return jsonify({"error": str(e)}), 400


@app.route('/status', methods=['GET'])
def status():
    """
    Get current status of the agent and pending work.
    
    Returns:
    {
      "status": "ready",
      "pending_approvals": 1,
      "approved_actions": 0,
      "rejected_actions": 0,
      "executions_completed": 0
    }
    """
    if not agent or not agent.hitl_gate:
        return jsonify({"status": "not_initialized"}), 503
    
    return jsonify({
        "status": "ready",
        "pending_approvals": len(agent.hitl_gate.get_pending_actions()),
        "approved_actions": len(agent.hitl_gate.get_approved_actions()),
        "rejected_actions": len(agent.hitl_gate.get_rejected_actions()),
        "executions_completed": len(execution_history)
    }), 200


@app.route('/', methods=['GET'])
def index():
    """Root endpoint with API documentation."""
    return jsonify({
        "name": "GitHub Issue Triage Agent — Phase 3",
        "version": "3.0.0",
        "status": "running",
        "endpoints": {
            "GET /health": "Health check",
            "POST /triage": "Classify GitHub issues",
            "GET /approvals": "Get pending approvals",
            "POST /approve": "Approve an action",
            "POST /reject": "Reject an action",
            "POST /execute": "Execute approved actions",
            "GET /status": "Get agent status"
        }
    }), 200


@app.errorhandler(404)
def not_found(e):
    """Handle 404 errors."""
    return jsonify({"error": "Endpoint not found"}), 404


@app.errorhandler(500)
def server_error(e):
    """Handle 500 errors."""
    return jsonify({"error": "Internal server error"}), 500


if __name__ == '__main__':
    # For local testing
    print("[STARTUP] GitHub Issue Triage Agent — Phase 3")
    print("[INFO] Starting Flask development server...")
    print("[INFO] Visit http://localhost:8080 to see endpoints")
    
    # Get port from environment or default to 8080
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)