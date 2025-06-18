#!/usr/bin/env python3
"""
Module 1: Basic MCP Server - Starter Code
"""
from dotenv import load_dotenv
import json
import subprocess
from pathlib import Path
import os
import sys
from github import Github
from typing import Optional
import aiohttp

from mcp.server.fastmcp import FastMCP
load_dotenv()

# Initialize the FastMCP server
mcp = FastMCP("pr-agent")

# PR template directory (shared across all modules)
if getattr(sys, 'frozen', False):
    # Running in a PyInstaller bundle
    # In one-file mode, sys._MEIPASS is the path to the temp directory where data is extracted
    # In one-folder mode, Path(__file__).parent is the app directory
    TEMPLATES_DIR = Path(sys._MEIPASS if hasattr(sys, '_MEIPASS') else Path(__file__).parent) / "templates"
    EVENTS_FILE = Path("..") / "github_events.json"
else:
    # Running in a regular Python environment
    TEMPLATES_DIR = Path(__file__).parent / "templates"
    EVENTS_FILE = Path("github_events.json")



# Default PR templates
DEFAULT_TEMPLATES = {
    "bug.md": "Bug Fix",
    "feature.md": "Feature",
    "docs.md": "Documentation",
    "refactor.md": "Refactor",
    "test.md": "Test",
    "performance.md": "Performance",
    "security.md": "Security"
}

# Type mapping for PR templates
TYPE_MAPPING = {
    "bug": "bug.md",
    "fix": "bug.md",
    "feature": "feature.md",
    "enhancement": "feature.md",
    "docs": "docs.md",
    "documentation": "docs.md",
    "refactor": "refactor.md",
    "cleanup": "refactor.md",
    "test": "test.md",
    "testing": "test.md",
    "performance": "performance.md",
    "optimization": "performance.md",
    "security": "security.md"
}

EVENTS_URL = "http://localhost:8080/events"

async def _get_events():
    """Fetch events from the EVENTS_URL endpoint and return the JSON data asynchronously."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(EVENTS_URL) as response:
                response.raise_for_status()
                return await response.json()
    except Exception as e:
        return {"error": f"Failed to fetch events: {e}"}

@mcp.tool()
async def analyze_file_changes(
    base_branch: str = "main",
    include_diff: bool = True,
    max_diff_lines: int = 500,
    working_directory: str | None = None
) -> str:
    """Get the full diff and list of changed files in the current git repository.
    
    Args:
        base_branch: Base branch to compare against (default: main)
        include_diff: Include the full diff content (default: true)
        max_diff_lines: Maximum number of diff lines to return (default: 500)
        working_directory: Optional working directory to use instead of fetching from MCP context
    """
    try:
        # context.session.send_log_message(level="info",data="Server started successfully")
        # Try to get working directory from roots first
        if working_directory is None:
            try:
                context = mcp.get_context()
                roots_result = await context.session.list_roots()
                # Get the first root - Claude Code sets this to the CWD
                root = roots_result.roots[0]
                # FileUrl object has a .path property that gives us the path directly
                working_directory = root.uri.path
            except Exception:
                # If we can't get roots, fall back to current directory
                pass
        
        # Use provided working directory or current directory
        cwd = working_directory if working_directory else os.getcwd()
        
        # Debug output
        debug_info = {
            "provided_working_directory": working_directory,
            "actual_cwd": cwd,
            "server_process_cwd": os.getcwd(),
            "server_file_location": str(Path(__file__).parent),
            "roots_check": None
        }
        
        # Add roots debug info
        try:
            context = mcp.get_context()
            roots_result = await context.session.list_roots()
            debug_info["roots_check"] = {
                "found": True,
                "count": len(roots_result.roots),
                "roots": [str(root.uri) for root in roots_result.roots]
            }
        except Exception as e:
            debug_info["roots_check"] = {
                "found": False,
                "error": str(e)
            }
        
        analysis = await _get_git_changes(cwd, base_branch, include_diff, max_diff_lines)
        analysis["_debug"] = debug_info
        
        return json.dumps(analysis, indent=2)
        
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def get_pr_templates() -> str:
    """List available PR templates with their content."""
    templates = [
        {
            "filename": filename,
            "type": template_type,
            "content": (TEMPLATES_DIR / filename).read_text()
        }
        for filename, template_type in DEFAULT_TEMPLATES.items()
    ]
    
    return json.dumps(templates, indent=2)


@mcp.tool()
async def suggest_template(changes_summary: str, change_type: str) -> str:
    """Let Claude analyze the changes and suggest the most appropriate PR template.
    
    Args:
        changes_summary: Your analysis of what the changes do
        change_type: The type of change you've identified (bug, feature, docs, refactor, test, etc.)
    """
    
    # Get available templates
    templates_response = await get_pr_templates()
    templates = json.loads(templates_response)
    
    # Find matching template
    template_file = TYPE_MAPPING.get(change_type.lower(), "feature.md")
    selected_template = next(
        (t for t in templates if t["filename"] == template_file),
        templates[0]  # Default to first template if no match
    )
    
    suggestion = {
        "recommended_template": selected_template,
        "reasoning": f"Based on your analysis: '{changes_summary}', this appears to be a {change_type} change.",
        "template_content": selected_template["content"],
        "usage_hint": "Claude can help you fill out this template based on the specific changes in your PR."
    }
    
    return json.dumps(suggestion, indent=2)


@mcp.tool()
async def create_github_pull_request(
    repo_name: str,
    title: str,
    body: str,
    head_branch: str,
    base_branch: str = "main"
) -> str:
    """Creates a pull request on GitHub.
    
    Args:
        repo_name: Repository name in format "owner/repo"
        title: PR title
        body: PR description
        head_branch: Source branch
        base_branch: Target branch (default: main)
    """
    github_token = os.getenv('GITHUB_TOKEN')
    if not github_token:
        return json.dumps({"error": "GitHub Token not found. Please set GITHUB_TOKEN environment variable."})

    try:
        g = Github(github_token)
        repo = g.get_repo(repo_name)
        
        pr = repo.create_pull(
            title=title,
            body=body,
            head=head_branch,
            base=base_branch
        )
        
        return json.dumps({"success": True, "pr_url": pr.html_url, "pr_number": pr.number}, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Failed to create PR: {e}"}, indent=2)


@mcp.tool()
async def get_local_file_changes(working_directory: str | None = None) -> str:
    """Get a summary of local file changes (staged, unstaged, untracked).
    
    Args:
        working_directory: Optional working directory to use instead of fetching from MCP context
    """
    try:
        if working_directory is None:
            context = mcp.get_context()
            roots_result = await context.session.list_roots()
            working_directory = roots_result.roots[0].uri.path
        
        cwd = working_directory if working_directory else os.getcwd()

        # Get status of files (staged, unstaged, untracked)
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True
        )
        status_output = status_result.stdout.strip().splitlines()

        # Get unstaged changes (diff of working tree vs index)
        unstaged_diff_result = subprocess.run(
            ["git", "diff"],
            cwd=cwd,
            capture_output=True,
            text=True
        )
        unstaged_diff = unstaged_diff_result.stdout

        # Get staged changes (diff of index vs HEAD)
        staged_diff_result = subprocess.run(
            ["git", "diff", "--staged"],
            cwd=cwd,
            capture_output=True,
            text=True
        )
        staged_diff = staged_diff_result.stdout

        return json.dumps({
            "status": status_output,
            "unstaged_diff": unstaged_diff,
            "staged_diff": staged_diff,
            "working_directory": cwd
        }, indent=2)
    
    except subprocess.CalledProcessError as e:
        return json.dumps({"error": f"Git command failed: {e.stderr}"})
    except Exception as e:
        return json.dumps({"error": f"Failed to get local file changes: {e}"})

# ===== Module 2: New GitHub Actions Tools =====

@mcp.tool()
async def get_recent_actions_events(limit: int = 10) -> str:
    """Get recent GitHub Actions events received via webhook.
    
    Args:
        limit: Maximum number of events to return (default: 10)
    """
    events = await _get_events()
    if isinstance(events, dict) and "error" in events:
        return json.dumps(events)
    if not events:
        return json.dumps({"message": f"No GitHub Actions events received yet. Looked at {EVENTS_URL}"})
    return json.dumps(events[-limit:], indent=2)


@mcp.tool()
async def get_workflow_status(workflow_name: Optional[str] = None) -> str:
    """Get the current status of GitHub Actions workflows.
    
    Args:
        workflow_name: Optional specific workflow name to filter by
    """
    events = await _get_events()
    if isinstance(events, dict) and "error" in events:
        return json.dumps(events)
    if not events:
        return json.dumps({"message": "No GitHub Actions events received yet. Looked at EVENTS_URL"})
    workflow_statuses = {}
    for event in events:
        if event.get("event_type") == "workflow_run":
            run = event.get("workflow_run", {})
            workflow_id = run.get("workflow_id")
            workflow_name_from_event = run.get("name")
            status = run.get("status")
            conclusion = run.get("conclusion")
            html_url = run.get("html_url")
            created_at = run.get("created_at")

            if workflow_id and workflow_name_from_event and created_at:
                # Only consider if a specific workflow_name is provided and matches
                if workflow_name and workflow_name.lower() != workflow_name_from_event.lower():
                    continue
                # Update if this is a newer run for the same workflow
                if workflow_id not in workflow_statuses or created_at > workflow_statuses[workflow_id]["created_at"]:
                    workflow_statuses[workflow_id] = {
                        "name": workflow_name_from_event,
                        "status": status,
                        "conclusion": conclusion,
                        "url": html_url,
                        "created_at": created_at
                    }
    # Convert dictionary to a list of statuses
    result = list(workflow_statuses.values())
    # Sort by creation date (most recent first)
    result.sort(key=lambda x: x["created_at"], reverse=True)
    return json.dumps(result, indent=2)

@mcp.tool()
async def send_slack_notification(message: str) -> str:
    """Send a formatted notification to the team Slack channel.
    
    Args:
        message: The message to send to Slack (supports Slack markdown)
    """
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook_url:
        return "Error: SLACK_WEBHOOK_URL environment variable not set"
    
    try:
        async with aiohttp.ClientSession() as session:
            payload = {"text": message, "mrkdwn": True}
            async with session.post(webhook_url, json=payload) as response:
                if response.status == 200:
                    return f"Slack notification sent successfully: {message[:50]}..."
                else:
                    resp_text = await response.text()
                    return f"Error sending Slack notification: {response.status} - {resp_text}"
    except Exception as e:
        return f"Error sending message: {str(e)}"


# ===== New Module 2: MCP Prompts =====

@mcp.prompt()
async def analyze_ci_results():
    """Analyze recent CI/CD results and provide insights."""
    return """Please analyze the recent CI/CD results from GitHub Actions:

1. First, call get_recent_actions_events() to fetch the latest CI/CD events
2. Then call get_workflow_status() to check current workflow states
3. Identify any failures or issues that need attention
4. Provide actionable next steps based on the results

Format your response as:
## CI/CD Status Summary
- **Overall Health**: [Good/Warning/Critical]
- **Failed Workflows**: [List any failures with links]
- **Successful Workflows**: [List recent successes]
- **Recommendations**: [Specific actions to take]
- **Trends**: [Any patterns you notice]"""


@mcp.prompt()
async def create_deployment_summary():
    """Generate a deployment summary for team communication."""
    return """Create a deployment summary for team communication:

1. Check workflow status with get_workflow_status()
2. Look specifically for deployment-related workflows
3. Note the deployment outcome, timing, and any issues

Format as a concise message suitable for Slack:

🚀 **Deployment Update**
- **Status**: [✅ Success / ❌ Failed / ⏳ In Progress]
- **Environment**: [Production/Staging/Dev]
- **Version/Commit**: [If available from workflow data]
- **Duration**: [If available]
- **Key Changes**: [Brief summary if available]
- **Issues**: [Any problems encountered]
- **Next Steps**: [Required actions if failed]

Keep it brief but informative for team awareness."""


@mcp.prompt()
async def generate_pr_status_report():
    """Generate a comprehensive PR status report including CI/CD results."""
    return """Generate a comprehensive PR status report:

1. Use analyze_file_changes() to understand what changed
2. Use get_workflow_status() to check CI/CD status
3. Use suggest_template() to recommend the appropriate PR template
4. Combine all information into a cohesive report

Create a detailed report with:

## 📋 PR Status Report

### 📝 Code Changes
- **Files Modified**: [Count by type - .py, .js, etc.]
- **Change Type**: [Feature/Bug/Refactor/etc.]
- **Impact Assessment**: [High/Medium/Low with reasoning]
- **Key Changes**: [Bullet points of main modifications]

### 🔄 CI/CD Status
- **All Checks**: [✅ Passing / ❌ Failing / ⏳ Running]
- **Test Results**: [Pass rate, failed tests if any]
- **Build Status**: [Success/Failed with details]
- **Code Quality**: [Linting, coverage if available]

### 📌 Recommendations
- **PR Template**: [Suggested template and why]
- **Next Steps**: [What needs to happen before merge]
- **Reviewers**: [Suggested reviewers based on files changed]

### ⚠️ Risks & Considerations
- [Any deployment risks]
- [Breaking changes]
- [Dependencies affected]"""


@mcp.prompt()
async def troubleshoot_workflow_failure():
    """Help troubleshoot a failing GitHub Actions workflow."""
    return """Help troubleshoot failing GitHub Actions workflows:

1. Use get_recent_actions_events() to find recent failures
2. Use get_workflow_status() to see which workflows are failing
3. Analyze the failure patterns and timing
4. Provide systematic troubleshooting steps

Structure your response as:

## 🔧 Workflow Troubleshooting Guide

### ❌ Failed Workflow Details
- **Workflow Name**: [Name of failing workflow]
- **Failure Type**: [Test/Build/Deploy/Lint]
- **First Failed**: [When did it start failing]
- **Failure Rate**: [Intermittent or consistent]

### 🔍 Diagnostic Information
- **Error Patterns**: [Common error messages or symptoms]
- **Recent Changes**: [What changed before failures started]
- **Dependencies**: [External services or resources involved]

### 💡 Possible Causes (ordered by likelihood)
1. **[Most Likely]**: [Description and why]
2. **[Likely]**: [Description and why]
3. **[Possible]**: [Description and why]

### ✅ Suggested Fixes
**Immediate Actions:**
- [ ] [Quick fix to try first]
- [ ] [Second quick fix]

**Investigation Steps:**
- [ ] [How to gather more info]
- [ ] [Logs or data to check]

**Long-term Solutions:**
- [ ] [Preventive measure]
- [ ] [Process improvement]

### 📚 Resources
- [Relevant documentation links]
- [Similar issues or solutions]"""

# ===== New Module 3: Slack Formatting Prompts =====

@mcp.prompt()
async def format_ci_failure_alert():
    """Create a Slack alert for CI/CD failures with rich formatting."""
    return """Format this GitHub Actions failure as a Slack message using ONLY Slack markdown syntax:

❌ *CI Failed* - [Repository Name]

> Brief summary of what failed

*Details:*
• Workflow: `workflow_name`
• Branch: `branch_name`  
• Commit: `commit_hash`

*Next Steps:*
• <https://github.com/test/repo/actions/runs/123|View Action Logs>

CRITICAL: Use EXACT Slack link format: <https://full-url|Link Text>
Examples:
- CORRECT: <https://github.com/user/repo|Repository>
- WRONG: [Repository](https://github.com/user/repo)
- WRONG: https://github.com/user/repo

Other Slack formats:
- *text* for bold (NOT **text**)
- `text` for code
- > text for quotes
- • for bullets"""


@mcp.prompt()
async def format_ci_success_summary():
    """Create a Slack message celebrating successful deployments."""
    return """Format this successful GitHub Actions run as a Slack message using ONLY Slack markdown syntax:

✅ *Deployment Successful* - [Repository Name]

> Brief summary of what was deployed

*Changes:*
• Key feature or fix 1
• Key feature or fix 2

*Links:*
• <https://github.com/user/repo|View Changes>

CRITICAL: Use EXACT Slack link format: <https://full-url|Link Text>
Examples:
- CORRECT: <https://github.com/user/repo|Repository>
- WRONG: [Repository](https://github.com/user/repo)
- WRONG: https://github.com/user/repo

Other Slack formats:
- *text* for bold (NOT **text**)
- `text` for code
- > text for quotes
- • for bullets"""

async def _get_git_changes(working_dir: str, base_branch: str, include_diff: bool, max_diff_lines: int) -> dict:
    """Helper function to get git changes and diff, callable outside of MCP context."""
    # Get changed files with status
    try:
        result = subprocess.run(
            ["git", "diff", "--name-status", f"{base_branch}...HEAD"],
            cwd=working_dir,
            capture_output=True,
            text=True,
            check=True
        )
        changed_files = [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
        stat_result = subprocess.run(
            ["git", "diff", "--stat", f"{base_branch}...HEAD"],
            cwd=working_dir,
            capture_output=True,
            text=True
        )
    except subprocess.CalledProcessError as e:
        return {"error": f"Git error: {e.stderr}"}
    except Exception as e:
        return {"error": f"Failed to get changed files or stats: {e}"}

    diff = ""
    truncated = False
    diff_line_count = 0
    if include_diff:
        try:
            diff_result = subprocess.run(
                ["git", "diff", f"{base_branch}...HEAD"],
                cwd=working_dir,
                capture_output=True,
                text=True,
                check=True
            )
            diff_lines = diff_result.stdout.splitlines()
            diff_line_count = len(diff_lines)
            if diff_line_count > max_diff_lines:
                diff = "\n".join(diff_lines[:max_diff_lines]) + "\n\n... Output truncated. Showing {max_diff_lines} of {len(diff_lines)} lines ...\n... Use max_diff_lines parameter to see more ..."
                truncated = True
            else:
                diff = diff_result.stdout
            
            commits_result = subprocess.run(
                ["git", "log", "--oneline", f"{base_branch}..HEAD"],
                capture_output=True,
                text=True,
                cwd=working_dir
            )
        except subprocess.CalledProcessError as e:
            return {"error": f"Git error: {e.stderr}"}
        except Exception as e:
            return {"error": f"Failed to get diff or commits: {e}"}

    return {
        "changed_files": changed_files,
        "statistics": stat_result.stdout,
        "diff": diff if include_diff else "Diff not included (set include_diff=true to see full diff)",
        "truncated": truncated,
        "diff_line_count": diff_line_count,
        "commits": commits_result.stdout if include_diff else None
    }


if __name__ == "__main__":
    mcp.run()