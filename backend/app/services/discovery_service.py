"""
DiscoveryService — automated project stack detection and AI team composition.

Phase 1 (deterministic): Reads config files (package.json, pyproject.toml,
pom.xml, build.gradle, Gemfile, go.mod, etc.), counts source file extensions,
and inspects Dockerfiles / docker-compose.yml to build an accurate picture of
the technology stack.

Phase 2 (AI-powered): Sends the detected stack plus a compact snapshot of the
project's README / CONTRIBUTING to the LLM proxy so Gemini can reason about
the *actual* work involved and suggest a team with role-level justifications.
Falls back to deterministic rules if the LLM is unavailable.
"""

import json
import os
import re
from collections import Counter
from pathlib import Path

from models import ProjectDiscovery
from sqlmodel import Session

# Directories that should never be walked (vendor code, build artefacts, VCS).
_SKIP_DIRS = {
    ".git",
    ".svn",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "dist",
    "build",
    ".next",
    ".nuxt",
    "target",
    ".gradle",
    ".idea",
    ".vscode",
    "coverage",
    ".pytest_cache",
    ".mypy_cache",
    "vendor",
}

# Extension → canonical language name.
_EXT_LANGUAGE: dict[str, str] = {
    ".py": "Python",
    ".pyw": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".c": "C",
    ".swift": "Swift",
    ".scala": "Scala",
    ".ex": "Elixir",
    ".exs": "Elixir",
    ".dart": "Dart",
}


def _walk_files(root: Path, max_files: int = 5000) -> list[Path]:
    """Yield up to *max_files* paths, skipping ignored directories."""
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skipped directories in-place so os.walk doesn't descend.
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            files.append(Path(dirpath) / name)
            if len(files) >= max_files:
                return files
    return files


def _detect_language(files: list[Path]) -> tuple[str, Counter]:
    """Return the dominant language and the full extension counter."""
    ext_counts: Counter = Counter()
    for f in files:
        lang = _EXT_LANGUAGE.get(f.suffix.lower())
        if lang:
            ext_counts[lang] += 1
    if not ext_counts:
        return "Unknown", ext_counts
    return ext_counts.most_common(1)[0][0], ext_counts


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:  # noqa: BLE001 - Unreadable discovery inputs are treated as unavailable.
        return {}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:  # noqa: BLE001 - Unreadable discovery inputs are treated as unavailable.
        return ""


def _find_config_files(root: Path, filename: str, max_depth: int = 3) -> list[Path]:
    """
    Search for *filename* within *max_depth* directory levels below root.
    Stops at directories in _SKIP_DIRS to avoid scanning vendor trees.
    """
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Compute current depth relative to root
        depth = len(Path(dirpath).relative_to(root).parts)
        if depth >= max_depth:
            dirnames.clear()
            continue
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        if filename in filenames:
            found.append(Path(dirpath) / filename)
    return found


def _detect_frameworks(root: Path, primary_lang: str) -> list[str]:
    """Detect frameworks by inspecting config files up to 3 levels deep."""
    frameworks: list[str] = []

    # ── JavaScript / TypeScript ──────────────────────────────────────────────
    for pkg_path in _find_config_files(root, "package.json"):
        data = _read_json(pkg_path)
        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        if "react" in deps and "React" not in frameworks:
            frameworks.append("React")
        if "vue" in deps and "Vue" not in frameworks:
            frameworks.append("Vue")
        if "svelte" in deps and "Svelte" not in frameworks:
            frameworks.append("Svelte")
        if "next" in deps and "Next.js" not in frameworks:
            frameworks.append("Next.js")
        if "nuxt" in deps and "Nuxt.js" not in frameworks:
            frameworks.append("Nuxt.js")
        if "express" in deps and "Express" not in frameworks:
            frameworks.append("Express")
        if "fastify" in deps and "Fastify" not in frameworks:
            frameworks.append("Fastify")
        if ("nestjs" in deps or "@nestjs/core" in deps) and "NestJS" not in frameworks:
            frameworks.append("NestJS")
        if (
            "angular" in deps or "@angular/core" in deps
        ) and "Angular" not in frameworks:
            frameworks.append("Angular")
        if "vite" in deps and "Vite" not in frameworks:
            frameworks.append("Vite")

    # ── Python ───────────────────────────────────────────────────────────────
    for pyproject_path in _find_config_files(root, "pyproject.toml"):
        content = _read_text(pyproject_path).lower()
        if "fastapi" in content and "FastAPI" not in frameworks:
            frameworks.append("FastAPI")
        if "django" in content and "Django" not in frameworks:
            frameworks.append("Django")
        if "flask" in content and "Flask" not in frameworks:
            frameworks.append("Flask")
        if (
            "langgraph" in content or "langchain" in content
        ) and "LangGraph/LangChain" not in frameworks:
            frameworks.append("LangGraph/LangChain")
        if "sqlalchemy" in content and "SQLAlchemy" not in frameworks:
            frameworks.append("SQLAlchemy")

    for req_path in _find_config_files(root, "requirements.txt"):
        content = _read_text(req_path).lower()
        if "fastapi" in content and "FastAPI" not in frameworks:
            frameworks.append("FastAPI")
        if "django" in content and "Django" not in frameworks:
            frameworks.append("Django")
        if "flask" in content and "Flask" not in frameworks:
            frameworks.append("Flask")
        if (
            "langgraph" in content or "langchain" in content
        ) and "LangGraph/LangChain" not in frameworks:
            frameworks.append("LangGraph/LangChain")

    # ── Java / Kotlin ─────────────────────────────────────────────────────────
    for pom_path in _find_config_files(root, "pom.xml"):
        content = _read_text(pom_path)
        if (
            "spring-boot" in content or "spring-web" in content
        ) and "Spring Boot" not in frameworks:
            frameworks.append("Spring Boot")

    for gradle_name in ("build.gradle", "build.gradle.kts"):
        for gradle_path in _find_config_files(root, gradle_name):
            content = _read_text(gradle_path)
            if "spring" in content.lower() and "Spring Boot" not in frameworks:
                frameworks.append("Spring Boot")

    # ── Ruby ──────────────────────────────────────────────────────────────────
    for gemfile_path in _find_config_files(root, "Gemfile"):
        content = _read_text(gemfile_path)
        if "rails" in content.lower() and "Ruby on Rails" not in frameworks:
            frameworks.append("Ruby on Rails")

    # ── Go ────────────────────────────────────────────────────────────────────
    for gomod_path in _find_config_files(root, "go.mod"):
        content = _read_text(gomod_path)
        if "gin-gonic" in content and "Gin" not in frameworks:
            frameworks.append("Gin")
        if "labstack/echo" in content and "Echo" not in frameworks:
            frameworks.append("Echo")
        if "gofiber" in content and "Fiber" not in frameworks:
            frameworks.append("Fiber")

    return list(dict.fromkeys(frameworks))  # preserve first-seen order, no duplicates


def _detect_databases(root: Path) -> list[str]:
    """Scan config files (root + subdirs) and docker-compose for database clues."""
    databases: set[str] = set()
    hints = [
        (r"postgres|postgresql|pgvector", "PostgreSQL"),
        (r"mysql|mariadb", "MySQL"),
        (r"mongodb|mongoose|motor", "MongoDB"),
        (r"redis", "Redis"),
        (r"neo4j", "Neo4j"),
        (r"sqlite", "SQLite"),
        (r"elasticsearch|opensearch", "Elasticsearch"),
        (r"cassandra", "Cassandra"),
        (r"dynamodb", "DynamoDB"),
    ]
    # Build candidate file list: root-level configs + known sub-configs
    scan_paths: list[Path] = [
        root / "docker-compose.yml",
        root / "docker-compose.yaml",
        root / ".env",
        root / ".env.example",
        *_find_config_files(root, "pyproject.toml"),
        *_find_config_files(root, "requirements.txt"),
        *_find_config_files(root, "package.json"),
        *_find_config_files(root, "application.yml"),
        *_find_config_files(root, "application.properties"),
        *_find_config_files(root, "database.yml"),
        *_find_config_files(root, ".env"),
        *_find_config_files(root, ".env.example"),
    ]
    for path in scan_paths:
        if not path.exists() or not path.is_file():
            continue
        content = _read_text(path).lower()
        for pattern, db_name in hints:
            if re.search(pattern, content):
                databases.add(db_name)
    return sorted(databases)


def _detect_infra(root: Path) -> dict:
    """Detect containerisation, CI, cloud, and IaC tooling."""
    infra: dict[str, bool] = {}
    infra["docker"] = (root / "Dockerfile").exists() or any(root.glob("*/Dockerfile"))
    infra["docker_compose"] = (root / "docker-compose.yml").exists() or (
        root / "docker-compose.yaml"
    ).exists()
    infra["kubernetes"] = any(root.glob("**/*.yaml")) and any(
        "kind:" in _read_text(p)
        for p in root.glob("**/*.yaml")
        if "k8s" in str(p) or "kubernetes" in str(p)
    )
    infra["github_actions"] = (root / ".github" / "workflows").is_dir()
    infra["terraform"] = any(root.glob("**/*.tf"))
    infra["helm"] = any(root.glob("**/Chart.yaml"))
    return {k: v for k, v in infra.items() if v}


def _estimate_complexity(files: list[Path], lang_counts: Counter) -> str:
    """Estimate project complexity from file count and language diversity."""
    total = len(files)
    n_langs = len(lang_counts)
    if total > 500 or n_langs >= 4:
        return "High"
    if total > 100 or n_langs >= 2:
        return "Medium"
    return "Low"


def _build_team(
    primary_lang: str,
    frameworks: list[str],
    databases: list[str],
    infra: dict,
    complexity: str,
) -> list[dict]:
    """
    Compose an AI engineering team tailored to the detected stack.

    Rules:
    - Always include PO, Architect, and at least one Developer.
    - Add a DevOps agent when Docker/K8s/Terraform is detected.
    - Add a Data/ML agent when AI frameworks (LangGraph, etc.) are present.
    - Scale to Staff seniority for High complexity.
    - Specialties are derived from actual detected technologies.
    """
    seniority_map = {"High": "Staff", "Medium": "Senior", "Low": "Mid"}
    dev_seniority = seniority_map[complexity]

    # Build specialty strings from real detections.
    fw_str = "/".join(frameworks[:2]) if frameworks else primary_lang
    db_str = "/".join(databases[:2]) if databases else "SQL"
    backend_langs = {
        "Python",
        "Java",
        "Go",
        "Rust",
        "Ruby",
        "PHP",
        "C#",
        "Kotlin",
        "Scala",
    }
    frontend_langs = {"TypeScript", "JavaScript"}

    team = [
        {
            "role": "PO",
            "seniority": "Senior",
            "specialty": "Product Management & Backlog",
        },
        {
            "role": "Architect",
            "seniority": dev_seniority,
            "specialty": f"{fw_str}/{db_str} Architecture",
        },
    ]

    # Frontend developer if JS/TS is present
    if primary_lang in frontend_langs or any(
        f in frameworks for f in ("React", "Vue", "Angular", "Svelte", "Next.js")
    ):
        team.append(
            {
                "role": "Dev",
                "seniority": dev_seniority,
                "specialty": f"Frontend/{fw_str}",
            }
        )

    # Backend developer
    if primary_lang in backend_langs or any(
        f in frameworks
        for f in ("FastAPI", "Django", "Flask", "Spring Boot", "Express", "NestJS")
    ):
        be_specialty = f"Backend/{primary_lang}" + (
            f"/{frameworks[0]}" if frameworks else ""
        )
        team.append(
            {"role": "Dev", "seniority": dev_seniority, "specialty": be_specialty}
        )
    elif primary_lang not in frontend_langs:
        # Catch-all backend if nothing matched above
        team.append(
            {
                "role": "Dev",
                "seniority": dev_seniority,
                "specialty": f"Backend/{primary_lang}",
            }
        )

    # AI/ML agent when AI frameworks detected
    if any(f in " ".join(frameworks) for f in ("LangGraph", "LangChain", "ML", "AI")):
        team.append(
            {"role": "Dev", "seniority": "Staff", "specialty": "AI/ML Engineering"}
        )

    # DevOps when infrastructure tooling detected
    if infra.get("docker") or infra.get("kubernetes") or infra.get("terraform"):
        infra_specialty = "/".join(
            k
            for k in ("Docker", "K8s", "Terraform")
            if infra.get(k.lower().replace("k8s", "kubernetes"))
        )
        team.append(
            {
                "role": "DevOps",
                "seniority": dev_seniority,
                "specialty": infra_specialty or "Cloud Infrastructure",
            }
        )

    # Always add QA
    team.append(
        {
            "role": "QA",
            "seniority": "Senior",
            "specialty": "Automated Testing & Quality",
        }
    )

    # Scrum Master only for High complexity
    if complexity == "High":
        team.append(
            {"role": "SM", "seniority": "Senior", "specialty": "Agile Delivery"}
        )

    return team


# ── LLM-powered team suggestion ───────────────────────────────────────────────

_TEAM_PROMPT = """\
You are an expert engineering manager at an AI software factory.

A new project has been scanned. Based on the stack context below, suggest the
optimal AI agent team to build and maintain this project.

## Detected Stack
{stack_summary}

## Project Context (README excerpt)
{readme_excerpt}

## Available Models (current live catalogue — choose ONLY from this list)
{model_catalog}

## Assignment Guidelines
- strategic tier  → PO, Architect  (complex decisions, stakeholder impact)
- balanced tier   → SM, Security   (coordination, reviews, risk analysis)
- code tier       → Dev, QA, DevOps, Data  (primary output is code/tests/scripts)
- fast/preview    → avoid unless no better option exists

## Instructions
Return ONLY a valid JSON array — no markdown, no explanation outside the array.
Each element is an agent object with EXACTLY these fields:

- "role"         : one of PO, SM, Architect, Dev, QA, DevOps, Security, Data
- "seniority"    : one of Junior, Mid, Senior, Staff
- "specialty"    : concise 2-6 word focus area derived from the ACTUAL detected stack
- "model"        : one model id from the catalogue above (must match exactly)
- "system_prompt": A detailed paragraph (4-8 sentences) written in first person that defines:
                   * This agent's personality and communication style
                   * Their core responsibilities in THIS specific project
                   * The technologies they specialise in (from the detected stack)
                   * How they interact with other agents and escalate decisions
- "reasoning"    : one sentence explaining why this role + model choice is right for THIS project

Constraints:
- 3 to 8 agents maximum — do NOT pad with unnecessary roles
- Always include PO, Architect, and at least one Dev
- Use Staff seniority only for High complexity projects
- Prefer the cheapest model that can handle the role's cognitive demands
- Do NOT add markdown fences or any text outside the JSON array
"""


def _build_dynamic_catalog(models: list[dict]) -> tuple[str, set[str]]:
    """
    Build a human-readable model catalog string and a set of valid model IDs
    from the live list returned by the proxy.

    Returns (catalog_text, valid_model_ids).
    """
    tier_order = ["strategic", "balanced", "code", "fast", "preview"]
    tier_labels = {
        "strategic": "STRATEGIC — deep reasoning (expensive, use sparingly)",
        "balanced": "BALANCED  — fast reasoning, coordination, reviews",
        "code": "CODE      — specialised code generation (cheapest, use for Dev/QA/DevOps/Data)",
        "fast": "FAST      — lightweight, quick responses",
        "preview": "PREVIEW   — experimental, may be unstable (avoid unless necessary)",
    }

    grouped: dict[str, list[dict]] = {t: [] for t in tier_order}
    for m in models:
        tier = m.get("tier", "balanced")
        if tier not in grouped:
            tier = "balanced"
        grouped[tier].append(m)

    lines = ["Available models (fetched live — only choose IDs listed here):\n"]
    valid_ids: set[str] = set()
    for tier in tier_order:
        entries = grouped[tier]
        if not entries:
            continue
        lines.append(f"{tier_labels[tier]}:")
        for m in sorted(entries, key=lambda x: x["id"]):
            lines.append(f"  - {m['id']:<40} {m['description']}")
            valid_ids.add(m["id"])
        lines.append("")

    return "\n".join(lines), valid_ids


def _read_readme(root: Path, max_chars: int = 1500) -> str:
    """Return the first *max_chars* characters of the project README, if any."""
    for name in ("README.md", "README.rst", "README.txt", "README"):
        candidate = root / name
        if candidate.exists():
            return _read_text(candidate)[:max_chars]
    return "(no README found)"


def _ai_suggest_team(
    detected_stack: dict,
    root: Path,
    llm_proxy_url: str,
) -> list[dict] | None:
    """
    Ask the LLM proxy to reason about the project and suggest a team.

    Workflow:
    1. Fetch the live model catalogue from the proxy (so the AI always sees
       current, non-deprecated models and their capability tiers).
    2. Build a dynamic catalog string and valid model ID set from that list.
    3. Ask the orchestrator model (also chosen dynamically) to produce a JSON
       team where every agent has an appropriate model, system_prompt, and
       reasoning.
    4. Validate and normalise the response; fall back to rules on any error.

    Returns a list of agent dicts on success, or ``None`` on failure.
    """
    try:
        import logging

        from llm_proxy_client import LLMProxyClient

        log = logging.getLogger("fabrique-backend")

        client = LLMProxyClient(base_url=llm_proxy_url)

        # ── Step 1: fetch live model catalogue ───────────────────────────────
        catalogue_data = client.get_available_models()
        models = catalogue_data.get("models", [])
        # Orchestrator: fastest stable non-preview model for meta-tasks
        orchestrator_model = catalogue_data.get("orchestrator", "gemini-3.8-flash")

        if not models:
            log.warning("Empty model catalogue from proxy — falling back to rules")
            return None

        log.info(
            "Model catalogue: %d models, orchestrator=%s",
            len(models),
            orchestrator_model,
        )

        # ── Step 2: build dynamic catalog string ─────────────────────────────
        catalog_text, valid_model_ids = _build_dynamic_catalog(models)

        # ── Step 3: build and send prompt ────────────────────────────────────
        stack_summary = (
            f"Primary language: {detected_stack['language']}\n"
            f"All languages: {', '.join(f'{k} ({v} files)' for k, v in detected_stack.get('all_languages', {}).items())}\n"
            f"Frameworks: {', '.join(detected_stack['frameworks']) or 'none detected'}\n"
            f"Databases: {', '.join(detected_stack['databases']) or 'none detected'}\n"
            f"Infra: {', '.join(detected_stack['infra']) or 'none detected'}\n"
            f"Complexity: {detected_stack['complexity']} ({detected_stack['file_count']} files)"
        )
        readme = _read_readme(root)
        prompt = _TEAM_PROMPT.format(
            stack_summary=stack_summary,
            readme_excerpt=readme,
            model_catalog=catalog_text,
        )

        result = client.chat(
            messages=[{"role": "user", "content": prompt}],
            model=orchestrator_model,
            role="Architect",
        )

        if result.get("error"):
            log.warning("LLM team suggestion failed: %s", result["error"])
            return None

        content = (
            result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        )

        # Strip accidental markdown fences
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)

        team = json.loads(content)
        if not isinstance(team, list) or not team:
            log.warning("LLM returned unexpected team shape: %s", type(team))
            return None

        # ── Step 4: validate and normalise ───────────────────────────────────
        valid_roles = {
            "PO",
            "SM",
            "Architect",
            "Dev",
            "QA",
            "DevOps",
            "Security",
            "Data",
        }
        valid_seniorities = {"Junior", "Mid", "Senior", "Staff"}

        # Build a quick tier lookup for fallback model selection
        _model_tier: dict[str, str] = {
            m["id"]: m.get("tier", "balanced") for m in models
        }
        best_strategic = next(
            (m["id"] for m in models if m.get("tier") == "strategic"),
            orchestrator_model,
        )
        best_code = next(
            (m["id"] for m in models if m.get("tier") == "code"), orchestrator_model
        )
        code_roles = {"Dev", "QA", "DevOps", "Data"}

        normalised = []
        for agent in team:
            role = agent.get("role", "Dev")
            if role not in valid_roles:
                role = "Dev"
            seniority = agent.get("seniority", "Senior")
            if seniority not in valid_seniorities:
                seniority = "Senior"
            model = agent.get("model", "")
            if model not in valid_model_ids:
                # LLM hallucinated a model — assign sensible default
                model = best_code if role in code_roles else best_strategic
            specialty = str(agent.get("specialty", ""))[:80]
            normalised.append(
                {
                    "role": role,
                    "seniority": seniority,
                    "specialty": specialty,
                    "model": model,
                    "system_prompt": str(agent.get("system_prompt", ""))[:1500],
                    "reasoning": str(agent.get("reasoning", ""))[:300],
                    "persona": specialty,
                }
            )

        log.info(
            "AI team: %d agents | %s",
            len(normalised),
            ", ".join(f"{a['role']}→{a['model']}" for a in normalised),
        )
        return normalised

    except Exception as exc:  # noqa: BLE001 - Fall back to the default team if AI discovery fails.
        import logging

        logging.getLogger("fabrique-backend").warning(
            "AI team suggestion error (will use rule-based fallback): %s", exc
        )
        return None


class DiscoveryService:
    """
    Scans a project directory and builds an accurate technology stack profile,
    then recommends an AI engineering team sized and specialised for that stack.

    Phase 1 is deterministic (filesystem walk + config-file parsing).
    Phase 2 uses the LLM proxy to reason about the project and produce a team
    with per-role justifications.  If the LLM is unavailable the service falls
    back to the rule-based ``_build_team()`` function automatically.

    Args:
        session:       Active SQLModel session used for persisting the discovery result.
        llm_proxy_url: Base URL of the internal LLM proxy (default: env var LLM_PROXY_URL).
    """

    def __init__(self, session: Session, llm_proxy_url: str | None = None):
        self.session = session
        self.llm_proxy_url = llm_proxy_url or os.getenv(
            "LLM_PROXY_URL", "http://localhost:5100"
        )

    def discover_project_team(
        self,
        company_id: int | None,
        project_path: str,
        stored_path: str | None = None,
        project_name: str | None = None,
    ):
        """
        Scan a project path and recommend an AI engineering team.

        Phase 1 — deterministic scan:
        - Walks up to 5 000 source files to determine the dominant language.
        - Reads package.json, pyproject.toml, pom.xml, Gemfile, go.mod, etc.
        - Inspects docker-compose.yml and .env for database services.
        - Detects CI, IaC, and containerisation tooling.

        Phase 2 — AI suggestion:
        - Sends the detected stack + README excerpt to the LLM proxy.
        - LLM returns a team with per-role reasoning.
        - Falls back to rule-based team if LLM is unavailable.

        Args:
            company_id:   Pass ``None`` for pre-creation discovery (no DB write).
            project_path: Filesystem path to the project root to analyse.
            stored_path:  The project's path on the user's machine when
                          *project_path* is a local mirror of it (a daemon
                          snapshot); recorded instead of *project_path*.
            project_name: The project's folder name, for the same case.

        Returns:
            Tuple of ``(discovery_orm_row_or_none, detected_stack_dict, suggested_team_list)``.
        """
        root = Path(project_path).expanduser().resolve()

        if not root.is_dir():
            raise ValueError(
                f"Project path does not exist or is not a directory: {root}"
            )

        folder_name = project_name or root.name or "New Project"

        # ── Phase 1: deterministic filesystem scan ────────────────────────────
        files = _walk_files(root)
        primary_lang, lang_counts = _detect_language(files)
        frameworks = _detect_frameworks(root, primary_lang)
        databases = _detect_databases(root)
        infra = _detect_infra(root)
        complexity = _estimate_complexity(files, lang_counts)

        detected_stack = {
            "name": folder_name,
            "language": primary_lang,
            "all_languages": dict(lang_counts.most_common(5)),
            "frameworks": frameworks,
            "databases": databases,
            "infra": list(infra.keys()),
            "complexity": complexity,
            "file_count": len(files),
        }

        # ── Phase 2: AI team suggestion (with rule-based fallback) ────────────
        suggested_team = _ai_suggest_team(detected_stack, root, self.llm_proxy_url)
        if suggested_team is None:
            suggested_team = _build_team(
                primary_lang, frameworks, databases, infra, complexity
            )
            # Tag as rule-based so the frontend can show a different indicator
            detected_stack["team_source"] = "rules"
        else:
            detected_stack["team_source"] = "ai"

        discovery = None
        if company_id:
            discovery = ProjectDiscovery(
                company_id=company_id,
                project_path=stored_path or str(root),
                detected_stack=json.dumps(detected_stack),
                suggested_team=json.dumps(suggested_team),
                status="completed",
            )
            self.session.add(discovery)
            self.session.commit()
            self.session.refresh(discovery)

        return discovery, detected_stack, suggested_team
