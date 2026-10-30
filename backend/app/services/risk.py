"""
How much a delivery needs a person: a deterministic risk tier from its paths.

``classify`` reads file paths and returns ``low``, ``medium`` or ``high`` with
the reasons. ``high`` is a delivery that touches authentication, secrets,
payments or the CI pipeline; ``medium`` one that touches shell scripts,
database migrations, dependency manifests or container and infrastructure
files; anything else is ``low``. The tier is the highest any path reaches, so
adding files never lowers it, and size plays no part.

The paths come from the workspace daemon's report of what it wrote (an
observation) and from what the producer declared (a claim). Declared paths
can only raise the tier, never lower it, so taking both is safe. A producer
may also raise the tier itself with ``claims["risk"] = {"tier": ..., "reason":
...}``; a lower tier there is ignored. The daemon reports neither file modes
nor deletions, so executable bits and removed files are not classified.

A high tier sends an approved task to a person at every autonomy level
(``services/task_worker.py``): autonomy decides how much routine work goes
without a person, and this is not routine.
"""

import re
from collections.abc import Iterable
from typing import Any

RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"
_RANK = {RISK_LOW: 0, RISK_MEDIUM: 1, RISK_HIGH: 2}
_MAX_REASONS = 10

# Words in a path (split on separators and camelCase) that mark it.
_HIGH_WORDS = {
    "authentication": {
        "auth",
        "authn",
        "authz",
        "authentication",
        "authenticate",
        "authorization",
        "authorize",
        "login",
        "logout",
        "signin",
        "signup",
        "password",
        "passwords",
        "passwd",
        "jwt",
        "oauth",
        "oauth2",
        "sso",
        "saml",
        "rbac",
        "permission",
        "permissions",
    },
    "secrets": {"secret", "secrets", "credential", "credentials"},
    "payments": {
        "payment",
        "payments",
        "billing",
        "stripe",
        "checkout",
        "invoice",
        "invoices",
        "paypal",
    },
}
_SECRET_FILES = {
    ".env",
    ".npmrc",
    ".pypirc",
    ".netrc",
    "id_rsa",
    "id_ecdsa",
    "id_ed25519",
}
_SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".keystore", ".jks")
_CI_PREFIXES = (".github/workflows/", ".circleci/")
_CI_FILES = {".gitlab-ci.yml", "jenkinsfile", "azure-pipelines.yml"}

_SHELL_SUFFIXES = (".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd")
_MIGRATION_DIRS = {"migrations", "migration", "alembic"}
_DEPENDENCY_FILES = {
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "pyproject.toml",
    "poetry.lock",
    "pipfile",
    "pipfile.lock",
    "setup.py",
    "setup.cfg",
    "go.mod",
    "go.sum",
    "cargo.toml",
    "cargo.lock",
    "gemfile",
    "gemfile.lock",
}
_INFRA_SUFFIXES = (".tf", ".tfvars")


def _words(path: str) -> set[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", path)
    return {word for word in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if word}


def _classify_path(path: str) -> tuple[str, str] | None:
    """``(tier, area)`` for one path, or ``None`` when nothing marks it."""
    normalized = path.replace("\\", "/").lower().lstrip("/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    name = normalized.rsplit("/", 1)[-1]
    segments = set(normalized.split("/")[:-1])
    words = _words(path)

    if name in _SECRET_FILES or (
        name.startswith(".env.") and name not in {".env.example", ".env.sample"}
    ):
        return RISK_HIGH, "secrets"
    if name.endswith(_SECRET_SUFFIXES):
        return RISK_HIGH, "secrets"
    if normalized.startswith(_CI_PREFIXES) or name in _CI_FILES:
        return RISK_HIGH, "CI pipeline"
    for area, marks in _HIGH_WORDS.items():
        if words & marks:
            return RISK_HIGH, area

    if name.endswith(_SHELL_SUFFIXES):
        return RISK_MEDIUM, "shell script"
    if segments & _MIGRATION_DIRS or name.endswith(".sql"):
        return RISK_MEDIUM, "database migration"
    if name in _DEPENDENCY_FILES or (
        name.startswith("requirements") and name.endswith(".txt")
    ):
        return RISK_MEDIUM, "dependencies"
    if name.startswith(("dockerfile", "docker-compose", "compose.")) or name.endswith(
        _INFRA_SUFFIXES
    ):
        return RISK_MEDIUM, "containers and infrastructure"
    return None


def classify(paths: Iterable[str], declared_risk: Any = None) -> dict[str, Any]:
    """The tier of a delivery and the reasons for it.

    *declared_risk* is the producer's own ``{"tier", "reason"}``: it may raise
    the tier (with its reason quoted as the producer's), never lower it.
    """
    tier = RISK_LOW
    reasons: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if not isinstance(path, str) or not path or path in seen:
            continue
        seen.add(path)
        found = _classify_path(path)
        if found is None:
            continue
        path_tier, area = found
        if _RANK[path_tier] > _RANK[tier]:
            tier = path_tier
        if len(reasons) < _MAX_REASONS:
            reasons.append(f"{area}: {path}")

    if isinstance(declared_risk, dict):
        declared = str(declared_risk.get("tier") or "").strip().lower()
        reason = str(declared_risk.get("reason") or "").strip()
        if declared in _RANK and reason and _RANK[declared] > _RANK[tier]:
            tier = declared
            reasons.append(f"raised by the producer: {reason[:200]}")
    return {"tier": tier, "reasons": reasons}


def is_high(tier: str | None) -> bool:
    return tier == RISK_HIGH
