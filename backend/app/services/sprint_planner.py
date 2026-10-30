"""
Sprint planner service — AI-driven foundation sprint planning.

When a new company is bootstrapped, the **PO agent** analyses the discovered
project stack and produces a set of backlog items for "Sprint 0 — Foundations".
These items focus on documentation completeness, missing configuration, and
establishing the knowledge base that agents need to work effectively.

The service delegates to the LLM proxy using the PO agent's assigned model,
falling back to a deterministic task list when the LLM is unavailable.
"""

import json
import os
from pathlib import Path
from typing import Any

from llm_proxy_client import LLMProxyClient
from logging_config import logger

# ---------------------------------------------------------------------------
# Prompt template — the PO agent plans the foundation sprint
# ---------------------------------------------------------------------------

_FOUNDATION_PROMPT = """\
You are {agent_name}, a {seniority} Product Owner at an AI software factory.
Your team consists of these AI agents:

{team_roster}

A new project has just been onboarded. Your job is to plan "Sprint 0 — \
Foundations": a short sprint that ensures ALL documentation, configuration, \
and knowledge-base artifacts are complete so the team can work effectively.

## Detected Stack
{stack_summary}

## Existing Files in Project Root
{file_listing}

## Instructions

Analyse what documentation and configuration already exists vs what is missing.
Generate a backlog of **5 to 12 tasks** covering:

1. **Documentation verification & completion** — README, CONTRIBUTING, \
   ARCHITECTURE, API docs, deployment guides, changelog.
2. **Agent knowledge base** — each agent needs context docs for their role: \
   coding standards, testing strategy, CI/CD pipeline docs, security policies, \
   infrastructure diagrams.
3. **Project configuration** — verify .env.example, Docker configs, CI \
   pipelines, linter configs are present and correct.
4. **Foundational decisions** — document tech stack decisions, branching \
   strategy, release process.

For EACH task return a JSON object with these exact fields:
- "title": concise task title (max 80 chars)
- "description": 2-4 sentence description of what to do and the acceptance \
  criteria
- "priority": "critical" | "high" | "medium" | "low"
- "assignee": the agent ROLE best suited (one of: {available_roles})

Rules:
- Do NOT create tasks for documentation that already exists AND is complete.
- DO create tasks to UPDATE docs that exist but are clearly incomplete.
- Assign tasks to the agent whose role fits best (e.g. Architect for \
  architecture docs, DevOps for CI/CD docs, QA for testing strategy).
- The PO should own the README and CONTRIBUTING tasks.
- Return ONLY a valid JSON object with two keys:
  * "goal": a one-sentence sprint goal (max 120 chars)
  * "tasks": the JSON array of task objects
- No markdown fences, no text outside the JSON object.
"""

_EXECUTION_PROMPT = """\
You are {agent_name}, a {seniority} Product Owner preparing the NEXT executable sprint for an AI delivery team.

## Team Roster
{team_roster}

## Planning Objective
{objective}

## Scope Constraint
- Requested scope: {scope_size}
- Maximum backlog items allowed: {item_limit}

## Detected Stack
{stack_summary}

## Existing Files In Project Root
{file_listing}

## Instructions

Turn the objective into an executable sprint plan that the team can start immediately.

Return a JSON object with these exact keys:
- "sprint_name": concise sprint name, max 70 chars
- "goal": one-sentence sprint goal, max 140 chars
- "tasks": array of backlog items

For each task return an object with these exact fields:
- "title": concise task title, max 80 chars
- "description": 2-4 sentences with expected outcome and acceptance criteria
- "priority": "critical" | "high" | "medium" | "low"
- "assignee": one of: {available_roles}

Rules:
- Return between 3 and {item_limit} tasks.
- Break the objective into work that can actually be executed in one sprint.
- Prefer concrete, verifiable tasks over vague epics.
- If the request is too broad, include only the highest-value slice that fits the sprint.
- Do NOT create a single giant task that repeats the whole objective.
- Use the team roles realistically.
- Return ONLY valid JSON. No markdown fences, no commentary.
"""

_SELF_IMPROVEMENT_PROMPT = """\
You are {agent_name}, a {seniority} Product Owner improving your own AI software factory using Scrumban.

## Team Roster
{team_roster}

## Self-Improvement Mission
{objective}

## Scope Constraint
- Requested scope: {scope_size}
- Maximum backlog items allowed: {item_limit}

## Detected Stack
{stack_summary}

## Existing Files In Project Root
{file_listing}

## Scrumban Rules
- Pull the next highest-value bottleneck, do not plan a giant transformation.
- Keep work-in-progress bounded to changes that fit one sprint.
- Prefer incremental updates over rewrites.
- Preserve assets that are already correct, complete, and working.
- Improve or extend existing files/components before proposing replacement.
- Only propose removal when something is clearly redundant, harmful, or obsolete and the task includes verification.

## Instructions

Plan the next autonomous self-improvement sprint for this factory.

Return a JSON object with these exact keys:
- "sprint_name": concise sprint name, max 70 chars
- "goal": one-sentence sprint goal, max 140 chars
- "tasks": array of backlog items

For each task return an object with these exact fields:
- "title": concise task title, max 80 chars
- "description": 2-4 sentences with expected outcome and acceptance criteria
- "priority": "critical" | "high" | "medium" | "low"
- "assignee": one of: {available_roles}

Rules:
- Return between 3 and {item_limit} tasks.
- Target the factory's own bottlenecks in planning, orchestration, validation, governance, UX, or safe execution.
- Use Scrumban thinking: select the next constrained slice, make it flow, and define how to verify it before expanding scope.
- Do not propose deleting or replacing healthy artifacts just to "start fresh".
- If an area is already strong, leave it alone and move to the next bottleneck.
- Every task must include a concrete verification angle.
- Return ONLY valid JSON. No markdown fences, no commentary.
"""

_DEFAULT_EXECUTION_TEAM = [
    {
        "role": "PO",
        "name": "PO",
        "seniority": "Senior",
        "specialty": "product planning",
        "model": "",
    },
    {
        "role": "ScrumMaster",
        "name": "Scrum Master",
        "seniority": "Senior",
        "specialty": "delivery orchestration",
        "model": "",
    },
    {
        "role": "Developer",
        "name": "Developer",
        "seniority": "Senior",
        "specialty": "implementation",
        "model": "",
    },
    {
        "role": "QA",
        "name": "QA",
        "seniority": "Senior",
        "specialty": "quality assurance",
        "model": "",
    },
    {
        "role": "Architect",
        "name": "Architect",
        "seniority": "Senior",
        "specialty": "system design",
        "model": "",
    },
    {
        "role": "DevOps",
        "name": "DevOps",
        "seniority": "Senior",
        "specialty": "delivery infrastructure",
        "model": "",
    },
]


def _build_stack_summary(stack: dict[str, Any]) -> str:
    """Format the detected stack dict into a readable summary for the prompt."""
    parts = []
    if stack.get("language"):
        parts.append(f"Primary language: {stack['language']}")
    if stack.get("all_languages"):
        langs = ", ".join(f"{k} ({v} files)" for k, v in stack["all_languages"].items())
        parts.append(f"Languages: {langs}")
    if stack.get("frameworks"):
        parts.append(f"Frameworks: {', '.join(stack['frameworks'])}")
    if stack.get("databases"):
        parts.append(f"Databases: {', '.join(stack['databases'])}")
    if stack.get("infra"):
        parts.append(f"Infrastructure: {', '.join(stack['infra'])}")
    if stack.get("complexity"):
        parts.append(f"Complexity: {stack['complexity']}")
    if stack.get("file_count"):
        parts.append(f"Files scanned: {stack['file_count']}")
    return "\n".join(parts) if parts else "No stack data available."


def _list_root_files(project_path: str, max_files: int = 60) -> str:
    """List files in the project root (1 level deep) to help the PO assess docs."""
    try:
        root = Path(project_path)
        if not root.is_dir():
            return "(project path not accessible)"
        entries = []
        for entry in sorted(root.iterdir()):
            if entry.name.startswith(".git") and entry.name != ".gitignore":
                continue
            marker = "📁" if entry.is_dir() else "📄"
            entries.append(f"  {marker} {entry.name}")
            if len(entries) >= max_files:
                entries.append("  ... and more")
                break
        return "\n".join(entries) if entries else "(empty directory)"
    except Exception as e:  # noqa: BLE001 - Directory context is optional for sprint planning.
        logger.warning(f"Could not list project root: {e}")
        return "(could not read directory)"


def _build_team_roster(agents: list[dict[str, Any]]) -> str:
    """Format the agent list into a readable roster for the prompt."""
    lines = []
    for a in agents:
        role = a.get("role", "Unknown")
        name = a.get("name", "")
        seniority = a.get("seniority", "Senior")
        specialty = a.get("specialty", "")
        model = a.get("model", "unknown")
        label = f"{name} ({role})" if name else role
        lines.append(f"- {label}: {seniority}, specialty={specialty}, model={model}")
    return "\n".join(lines) if lines else "- (no agents defined)"


def _find_po_agent(agents: list[dict[str, Any]]) -> dict[str, Any]:
    """Find the PO agent; fall back to Architect, then first agent."""
    for role_pref in ("PO", "Architect"):
        for a in agents:
            if a.get("role") == role_pref:
                return a
    return (
        agents[0]
        if agents
        else {"role": "PO", "model": "", "name": "PO", "seniority": "Senior"}
    )


def _ensure_execution_team(agents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Guarantee a minimum delivery roster even when the company has no stored agents yet."""
    if agents:
        return agents
    return list(_DEFAULT_EXECUTION_TEAM)


def build_self_improvement_objective(
    company_name: str,
    detected_stack: dict[str, Any] | None = None,
    sprint_metrics: dict[str, Any] | None = None,
) -> str:
    """Build a bounded, data-driven objective for a self-improvement sprint."""
    stack = detected_stack or {}
    framework_summary = (
        ", ".join(stack.get("frameworks") or []) or "current application stack"
    )
    language_summary = stack.get("language") or "the detected primary language"
    base = (
        f"Inspect the current {company_name} codebase and improve the factory's own autonomous delivery loop using Scrumban. "
        f"Prioritize the next highest-value bottleneck affecting self-planning, orchestration reliability, runtime validation, "
        f"or safe artifact generation for the existing stack ({framework_summary}; primary language: {language_summary}). "
        "Preserve files, workflows, and behaviors that are already correct and complete; iterate by extending or refining them instead of rewriting them. "
        "Choose one bounded slice that can be implemented and verified within a single sprint, keep work-in-progress limited, and prefer changes that let the system improve itself with less human intervention."
    )

    if not sprint_metrics:
        return base

    signals: list[str] = []
    completion = sprint_metrics.get("completion_rate", 100)
    if completion < 80:
        signals.append(
            f"Last sprint completion rate was {completion}% — prioritize reducing task blocking and improving agent resilience."
        )
    rework = sprint_metrics.get("rework_cycles", 0)
    if rework > 3:
        signals.append(
            f"There were {rework} QA rework cycles — focus on improving first-pass output quality or tightening pre-review validation."
        )
    qa_failures = sprint_metrics.get("qa_failures", 0)
    if qa_failures > 2:
        signals.append(
            f"QA failed {qa_failures} times — consider hardening the quality gate or improving agent prompts."
        )
    blocked = sprint_metrics.get("blocked_tasks", 0)
    if blocked > 0:
        signals.append(
            f"{blocked} tasks ended blocked — improve error recovery, task decomposition, or agent fallback behavior."
        )
    for reason in (sprint_metrics.get("blocked_reasons") or [])[:2]:
        signals.append(f"Known block pattern: {reason}")

    if signals:
        return (
            base
            + "\n\nRetro signals from last sprint (use to focus improvement area):\n"
            + "\n".join(f"- {s}" for s in signals)
        )
    return base


# ---------------------------------------------------------------------------
# Fallback tasks when the LLM is unavailable
# ---------------------------------------------------------------------------

_FALLBACK_TASKS = [
    {
        "title": "Verify and complete README.md",
        "description": "Ensure the README includes: project description, setup instructions, "
        "architecture overview, contribution guidelines link, and license.",
        "priority": "critical",
        "assignee": "PO",
    },
    {
        "title": "Create or update CONTRIBUTING.md",
        "description": "Document the contribution workflow: branching strategy, commit conventions, "
        "code review process, and PR template.",
        "priority": "high",
        "assignee": "PO",
    },
    {
        "title": "Document system architecture",
        "description": "Create ARCHITECTURE.md with component diagram, data flow, service boundaries, "
        "and technology decisions with rationale.",
        "priority": "critical",
        "assignee": "Architect",
    },
    {
        "title": "Define coding standards and conventions",
        "description": "Document language-specific coding standards, naming conventions, file structure, "
        "and linter/formatter configuration.",
        "priority": "high",
        "assignee": "Dev",
    },
    {
        "title": "Create testing strategy document",
        "description": "Define testing pyramid: unit, integration, e2e test expectations, coverage "
        "targets, and test framework choices.",
        "priority": "high",
        "assignee": "QA",
    },
    {
        "title": "Document CI/CD pipeline and deployment process",
        "description": "Create deployment guide covering CI/CD pipeline stages, environment configuration, "
        "secrets management, and rollback procedures.",
        "priority": "high",
        "assignee": "DevOps",
    },
    {
        "title": "Verify environment configuration files",
        "description": "Ensure .env.example exists with all required variables documented, Docker configs "
        "are complete, and local dev setup is reproducible.",
        "priority": "medium",
        "assignee": "DevOps",
    },
    {
        "title": "Create security baseline document",
        "description": "Document authentication/authorization approach, secrets management policy, "
        "dependency scanning setup, and security review checklist.",
        "priority": "medium",
        "assignee": "Security",
    },
]


def _filter_fallback_tasks(agents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only fallback tasks whose assignee role exists in the team."""
    available_roles = {a.get("role") for a in agents}
    return [t for t in _FALLBACK_TASKS if t["assignee"] in available_roles]


def _build_execution_fallback(
    objective: str, agents: list[dict[str, Any]], scope_size: str
) -> dict[str, Any]:
    """Deterministic fallback when no planner model is available."""
    team = _ensure_execution_team(agents)
    available_roles = {a.get("role") for a in team}
    defaults = [
        {
            "title": "Refine sprint objective and acceptance criteria",
            "description": f"Turn the prompt into explicit delivery criteria, non-goals, and success checks. Base objective: {objective[:220]}",
            "priority": "critical",
            "assignee": "PO",
        },
        {
            "title": "Design implementation slice",
            "description": "Define the smallest architecture and execution slice that fits this sprint, including dependencies and guardrails.",
            "priority": "high",
            "assignee": "Architect",
        },
        {
            "title": "Implement highest-value workflow",
            "description": "Deliver the core implementation for the selected slice and keep changes bounded to what can be validated this sprint.",
            "priority": "critical",
            "assignee": "Developer",
        },
        {
            "title": "Validate behavior and regression risk",
            "description": "Review the deliverable, verify acceptance criteria, and block unsafe output instead of allowing low-quality completion.",
            "priority": "high",
            "assignee": "QA",
        },
    ]

    scoped_limit = {"S": 4, "M": 8, "L": 12}.get(scope_size.upper(), 8)
    tasks = [t for t in defaults if t["assignee"] in available_roles][:scoped_limit]
    if not tasks:
        tasks = defaults[: min(4, scoped_limit)]

    return {
        "sprint_name": f"Sprint - {objective[:40].strip() or 'Execution'}",
        "goal": f"Plan and execute the highest-value slice of: {objective[:90].strip()}",
        "tasks": tasks,
    }


def _build_self_improvement_fallback(
    company_name: str, agents: list[dict[str, Any]], scope_size: str
) -> dict[str, Any]:
    """Deterministic self-improvement backlog that preserves healthy artifacts."""
    team = _ensure_execution_team(agents)
    available_roles = {a.get("role") for a in team}
    defaults = [
        {
            "title": "Identify the next factory bottleneck",
            "description": "Review current orchestration, UX, and delivery signals to select the highest-value improvement slice. Capture explicit acceptance criteria and confirm what should remain untouched because it already works well.",
            "priority": "critical",
            "assignee": "PO",
        },
        {
            "title": "Design an incremental Scrumban change",
            "description": "Define the smallest process or architecture adjustment that improves flow without destabilizing healthy parts of the product. Make the change bounded enough to move across the board within one sprint.",
            "priority": "high",
            "assignee": "Architect",
        },
        {
            "title": "Implement the next constrained improvement",
            "description": "Apply the selected improvement by extending the current implementation instead of replacing good working assets. Keep the work focused on one bottleneck and wire it into the existing agent orchestration.",
            "priority": "critical",
            "assignee": "Developer",
        },
        {
            "title": "Validate flow and protect healthy behavior",
            "description": "Verify the improved slice and confirm that already-correct artifacts and workflows remain intact. Reject destructive churn and document any new operating rule needed for the next iteration.",
            "priority": "high",
            "assignee": "QA",
        },
    ]

    scoped_limit = {"S": 4, "M": 8, "L": 12}.get(scope_size.upper(), 8)
    tasks = [task for task in defaults if task["assignee"] in available_roles][
        :scoped_limit
    ]
    if not tasks:
        tasks = defaults[: min(4, scoped_limit)]

    return {
        "sprint_name": f"Sprint - Improve {company_name}",
        "goal": f"Improve {company_name} through one bounded Scrumban iteration without rewriting healthy assets.",
        "tasks": tasks,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def plan_foundation_sprint(
    company_name: str,
    agents: list[dict[str, Any]],
    detected_stack: dict[str, Any] | None,
    project_path: str | None,
) -> dict[str, Any]:
    """
    Have the PO agent plan "Sprint 0 — Foundations" via LLM.

    Args:
        company_name:   Display name of the company / project.
        agents:         List of agent dicts (role, name, model, seniority, specialty).
        detected_stack: Stack analysis from the discovery phase (may be None).
        project_path:   Filesystem path to the project root (may be None).

    Returns:
        Dict with ``"goal"`` (str) and ``"tasks"`` (list of backlog dicts).
        Each task has: title, description, priority, assignee.
    """
    po = _find_po_agent(agents)
    po_model = po.get("model", "")
    available_roles = sorted({a.get("role", "Dev") for a in agents})

    # If no LLM model or no stack data, return fallback immediately.
    if not po_model or not detected_stack:
        logger.info("No PO model or stack data — using fallback foundation tasks")
        return {
            "goal": f"Establish documentation and configuration foundations for {company_name}",
            "tasks": _filter_fallback_tasks(agents),
        }

    llm_url = os.getenv("LLM_PROXY_URL", "http://llm-proxy:5100")
    client = LLMProxyClient(base_url=llm_url)

    stack_summary = _build_stack_summary(detected_stack)
    file_listing = (
        _list_root_files(project_path) if project_path else "(no project path)"
    )
    team_roster = _build_team_roster(agents)

    prompt = _FOUNDATION_PROMPT.format(
        agent_name=po.get("name") or "PO",
        seniority=po.get("seniority", "Senior"),
        team_roster=team_roster,
        stack_summary=stack_summary,
        file_listing=file_listing,
        available_roles=", ".join(available_roles),
    )

    logger.info(f"PO planning foundation sprint with model={po_model}")

    try:
        result = client.chat(
            messages=[{"role": "user", "content": prompt}],
            model=po_model,
            role="PO",
        )

        if result.get("error"):
            logger.warning(f"LLM error during sprint planning: {result['error']}")
            return {
                "goal": f"Establish documentation and configuration foundations for {company_name}",
                "tasks": _filter_fallback_tasks(agents),
            }

        raw = result.get("choices", [{}])[0].get("message", {}).get("content", "")

        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        cleaned = cleaned.strip()

        parsed = json.loads(cleaned)

        goal = parsed.get("goal", f"Foundation sprint for {company_name}")
        tasks = parsed.get("tasks", [])

        valid_roles = set(available_roles)
        validated = []
        for t in tasks:
            if not isinstance(t, dict) or not t.get("title"):
                continue
            assignee = t.get("assignee", "PO")
            if assignee not in valid_roles:
                assignee = "PO"
            validated.append(
                {
                    "title": str(t["title"])[:80],
                    "description": str(t.get("description", ""))[:500],
                    "priority": t.get("priority", "medium")
                    if t.get("priority") in ("critical", "high", "medium", "low")
                    else "medium",
                    "assignee": assignee,
                }
            )

        if not validated:
            logger.warning("LLM returned no valid tasks — using fallback")
            return {
                "goal": goal,
                "tasks": _filter_fallback_tasks(agents),
            }

        logger.info(f"PO planned {len(validated)} foundation tasks")
        return {"goal": goal, "tasks": validated}

    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.warning(f"Failed to parse PO sprint plan: {e}")
        return {
            "goal": f"Establish documentation and configuration foundations for {company_name}",
            "tasks": _filter_fallback_tasks(agents),
        }
    except Exception as e:  # noqa: BLE001 - Planning failures use the deterministic fallback.
        logger.error(f"Unexpected error in sprint planning: {e}")
        return {
            "goal": f"Establish documentation and configuration foundations for {company_name}",
            "tasks": _filter_fallback_tasks(agents),
        }


def plan_execution_sprint(
    company_name: str,
    objective: str,
    scope_size: str,
    agents: list[dict[str, Any]],
    detected_stack: dict[str, Any] | None = None,
    project_path: str | None = None,
) -> dict[str, Any]:
    """Plan an executable sprint from a strategic prompt."""
    team = _ensure_execution_team(agents)
    po = _find_po_agent(team)
    po_model = po.get("model", "")
    normalized_scope = scope_size.upper()
    item_limit = {"S": 4, "M": 8, "L": 12}.get(normalized_scope, 8)
    available_roles = sorted({a.get("role", "Developer") for a in team})

    if not po_model:
        logger.info("No planning model available — using execution fallback")
        return _build_execution_fallback(objective, team, normalized_scope)

    llm_url = os.getenv("LLM_PROXY_URL", "http://llm-proxy:5100")
    client = LLMProxyClient(base_url=llm_url)
    client.timeout = 12
    client.max_retries = 0

    prompt = _EXECUTION_PROMPT.format(
        agent_name=po.get("name") or "PO",
        seniority=po.get("seniority", "Senior"),
        team_roster=_build_team_roster(team),
        objective=objective.strip(),
        scope_size=normalized_scope,
        item_limit=item_limit,
        stack_summary=_build_stack_summary(detected_stack or {}),
        file_listing=_list_root_files(project_path)
        if project_path
        else "(no project path)",
        available_roles=", ".join(available_roles),
    )

    logger.info(
        "PO planning execution sprint with model=%s scope=%s",
        po_model,
        normalized_scope,
    )

    try:
        result = client.chat(
            messages=[{"role": "user", "content": prompt}],
            model=po_model,
            role="PO",
        )

        if result.get("error"):
            logger.warning(
                "LLM error during execution sprint planning: %s", result["error"]
            )
            return _build_execution_fallback(objective, team, normalized_scope)

        raw = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        parsed = json.loads(cleaned.strip())

        sprint_name = str(
            parsed.get("sprint_name") or f"Sprint - {objective[:40].strip()}"
        )[:70]
        goal = str(parsed.get("goal") or objective.strip())[:140]
        tasks = parsed.get("tasks", [])

        valid_roles = set(available_roles)
        validated = []
        for task in tasks:
            if not isinstance(task, dict) or not task.get("title"):
                continue
            assignee = str(task.get("assignee", "PO"))
            if assignee not in valid_roles:
                assignee = "PO"
            validated.append(
                {
                    "title": str(task.get("title", ""))[:80],
                    "description": str(task.get("description", ""))[:500],
                    "priority": task.get("priority", "medium")
                    if task.get("priority") in ("critical", "high", "medium", "low")
                    else "medium",
                    "assignee": assignee,
                }
            )

        validated = validated[:item_limit]
        if len(validated) < 2:
            logger.warning(
                "Planner returned too few valid execution tasks — using fallback"
            )
            return _build_execution_fallback(objective, team, normalized_scope)

        return {
            "sprint_name": sprint_name,
            "goal": goal,
            "tasks": validated,
        }
    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        logger.warning("Failed to parse execution sprint plan: %s", exc)
        return _build_execution_fallback(objective, team, normalized_scope)
    except Exception as exc:  # noqa: BLE001 - Planning failures use the deterministic fallback.
        logger.error("Unexpected error planning execution sprint: %s", exc)
        return _build_execution_fallback(objective, team, normalized_scope)


def plan_self_improvement_sprint(
    company_name: str,
    objective: str,
    scope_size: str,
    agents: list[dict[str, Any]],
    detected_stack: dict[str, Any] | None = None,
    project_path: str | None = None,
) -> dict[str, Any]:
    """Plan a bounded self-improvement sprint using explicit preservation and Scrumban rules."""
    team = _ensure_execution_team(agents)
    po = _find_po_agent(team)
    po_model = po.get("model", "")
    normalized_scope = scope_size.upper()
    item_limit = {"S": 4, "M": 8, "L": 12}.get(normalized_scope, 8)
    available_roles = sorted({a.get("role", "Developer") for a in team})

    if not po_model:
        logger.info("No planning model available — using self-improvement fallback")
        return _build_self_improvement_fallback(company_name, team, normalized_scope)

    llm_url = os.getenv("LLM_PROXY_URL", "http://llm-proxy:5100")
    client = LLMProxyClient(base_url=llm_url)
    client.timeout = 12
    client.max_retries = 0

    prompt = _SELF_IMPROVEMENT_PROMPT.format(
        agent_name=po.get("name") or "PO",
        seniority=po.get("seniority", "Senior"),
        team_roster=_build_team_roster(team),
        objective=objective.strip(),
        scope_size=normalized_scope,
        item_limit=item_limit,
        stack_summary=_build_stack_summary(detected_stack or {}),
        file_listing=_list_root_files(project_path)
        if project_path
        else "(no project path)",
        available_roles=", ".join(available_roles),
    )

    logger.info(
        "PO planning self-improvement sprint with model=%s scope=%s",
        po_model,
        normalized_scope,
    )

    try:
        result = client.chat(
            messages=[{"role": "user", "content": prompt}],
            model=po_model,
            role="PO",
        )

        if result.get("error"):
            logger.warning(
                "LLM error during self-improvement sprint planning: %s", result["error"]
            )
            return _build_self_improvement_fallback(
                company_name, team, normalized_scope
            )

        raw = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        parsed = json.loads(cleaned.strip())

        sprint_name = str(
            parsed.get("sprint_name") or f"Sprint - Improve {company_name}"
        )[:70]
        goal = str(parsed.get("goal") or objective.strip())[:140]
        tasks = parsed.get("tasks", [])

        valid_roles = set(available_roles)
        validated = []
        for task in tasks:
            if not isinstance(task, dict) or not task.get("title"):
                continue
            assignee = str(task.get("assignee", "PO"))
            if assignee not in valid_roles:
                assignee = "PO"
            validated.append(
                {
                    "title": str(task.get("title", ""))[:80],
                    "description": str(task.get("description", ""))[:500],
                    "priority": task.get("priority", "medium")
                    if task.get("priority") in ("critical", "high", "medium", "low")
                    else "medium",
                    "assignee": assignee,
                }
            )

        validated = validated[:item_limit]
        if len(validated) < 2:
            logger.warning(
                "Planner returned too few valid self-improvement tasks — using fallback"
            )
            return _build_self_improvement_fallback(
                company_name, team, normalized_scope
            )

        return {
            "sprint_name": sprint_name,
            "goal": goal,
            "tasks": validated,
        }
    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        logger.warning("Failed to parse self-improvement sprint plan: %s", exc)
        return _build_self_improvement_fallback(company_name, team, normalized_scope)
    except Exception as exc:  # noqa: BLE001 - Planning failures use the deterministic fallback.
        logger.error("Unexpected error planning self-improvement sprint: %s", exc)
        return _build_self_improvement_fallback(company_name, team, normalized_scope)
