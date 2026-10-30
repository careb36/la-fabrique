import hashlib
import hmac
import os
import re
from datetime import UTC, datetime
from urllib.parse import quote, urlsplit

import httpx
from schemas import AgentRunCreate

GITHUB_API_URL = "https://api.github.com"
_CLAUDE_TRAILER = re.compile(r"Co-Authored-By:\s*Claude", re.IGNORECASE)
_DIFF_FILE = re.compile(r"^diff --git a/(.*?) b/(.*)$", re.MULTILINE)


class GitHubRateLimited(Exception):
    def __init__(self, reset_at: str | None = None):
        self.reset_at = reset_at
        super().__init__(
            f"GitHub API rate limit exceeded; reset at {reset_at or 'unknown'}"
        )


def verify_webhook_signature(
    secret: str, body: bytes, signature_header: str | None
) -> bool:
    if not isinstance(signature_header, str) or not signature_header.startswith(
        "sha256="
    ):
        return False
    supplied = signature_header[len("sha256=") :]
    if len(supplied) != hashlib.sha256().digest_size * 2:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, supplied)


def infer_producer(
    author_login: str, author_type: str | None, commit_messages: list[str]
) -> tuple[str, str]:
    login = author_login or "unknown"
    normalized_login = login.casefold()
    if normalized_login == "copilot" or normalized_login.endswith(
        "copilot-swe-agent[bot]"
    ):
        producer = "copilot"
    elif any(_CLAUDE_TRAILER.search(message) for message in commit_messages):
        producer = "claude-code"
    elif normalized_login.endswith("[bot]") or author_type == "Bot":
        producer = f"bot:{login}"
    else:
        producer = f"human:{login}"
    return producer, login


def _changed_files(diff_text: str) -> list[str]:
    return [match.group(2) for match in _DIFF_FILE.finditer(diff_text)]


def pr_to_agent_run_payload(
    *,
    company_id: int,
    owner: str,
    repo: str,
    pr: dict,
    commits: list[dict],
    diff_text: str,
) -> AgentRunCreate:
    commit_messages = [commit["commit"]["message"] for commit in commits]
    user = pr.get("user") or {}
    producer, raw_author = infer_producer(
        user.get("login") or "unknown",
        user.get("type"),
        commit_messages,
    )
    head = pr.get("head") or {}
    base = pr.get("base") or {}
    return AgentRunCreate(
        company_id=company_id,
        external_ref=f"github:{owner}/{repo}#{pr['number']}",
        producer=producer,
        model=None,
        subject={
            "repository": f"{owner}/{repo}",
            "base_branch": (base.get("ref") or ""),
            "head_branch": (head.get("ref") or ""),
            "head_sha": head.get("sha"),
            "pr_url": pr.get("html_url"),
            "changed_files": _changed_files(diff_text),
            "raw_author": raw_author,
            "inferred_producer": producer,
        },
        claims={
            "title": pr["title"],
            "body": pr.get("body") or "",
            "commit_messages": commit_messages,
        },
        artifact=diff_text,
        started_at=pr.get("created_at"),
        finished_at=pr.get("merged_at") or pr.get("closed_at"),
    )


def should_include(producer: str, inclusion_rule: str) -> bool:
    if inclusion_rule == "all":
        return True
    is_bot = producer in {"copilot", "claude-code"} or producer.startswith("bot:")
    if inclusion_rule == "bots_only":
        return is_bot
    if inclusion_rule == "non_bots":
        return not is_bot
    raise ValueError(f"unsupported GitHub inclusion rule: {inclusion_rule}")


def _default_token() -> str | None:
    from config import settings

    return os.getenv("GITHUB_TOKEN") or settings.GITHUB_TOKEN


def _headers(token: str | None, accept: str) -> dict[str, str]:
    headers = {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}
    resolved_token = token or _default_token()
    if resolved_token:
        headers["Authorization"] = "Bearer " + resolved_token
    return headers


def _next_link(response: httpx.Response) -> str | None:
    for link in response.headers.get("Link", "").split(","):
        match = re.match(r'\s*<([^>]+)>;\s*rel="([^"]+)"', link)
        if match and match.group(2) == "next":
            return match.group(1)
    return None


def _get(
    url: str, *, token: str | None, accept: str, params: dict | None = None
) -> httpx.Response:
    response = httpx.get(
        url, headers=_headers(token, accept), params=params, timeout=30.0
    )
    if (
        response.status_code in (403, 429)
        and response.headers.get("X-RateLimit-Remaining") == "0"
    ):
        raise GitHubRateLimited(response.headers.get("X-RateLimit-Reset"))
    response.raise_for_status()
    return response


def _paged_json(url: str, *, token: str | None, params: dict | None = None):
    results = []
    visited = set()
    next_url = url
    origin = urlsplit(url)[:2]
    first_page = True
    while next_url and next_url not in visited:
        if urlsplit(next_url)[:2] != origin:
            raise ValueError("GitHub pagination link changed API origin")
        visited.add(next_url)
        response = _get(
            next_url,
            token=token,
            accept="application/vnd.github+json",
            params=params if first_page else None,
        )
        first_page = False
        data = response.json()
        if not isinstance(data, list):
            raise ValueError("GitHub API returned an unexpected paginated response")  # noqa: TRY004 - Preserve the adapter's response-value error contract.
        results.extend(data)
        next_url = _next_link(response)
    return results


def _parse_datetime(value) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed


def fetch_pull_requests(
    owner: str,
    repo: str,
    *,
    token: str | None = None,
    state: str = "all",
    since: str | None = None,
    base_url: str = GITHUB_API_URL,
) -> list[dict]:
    url = (
        f"{base_url.rstrip('/')}/repos/{quote(owner, safe='')}/"
        f"{quote(repo, safe='')}/pulls"
    )
    pulls = _paged_json(
        url,
        token=token,
        params={
            "state": state,
            "per_page": 100,
            "sort": "created",
            "direction": "asc",
        },
    )
    since_dt = _parse_datetime(since)
    if since_dt is None:
        return pulls
    filtered = []
    for pr in pulls:
        created_at = _parse_datetime(pr.get("created_at"))
        if created_at is None:
            continue
        comparable_created = (
            created_at.replace(tzinfo=UTC) if created_at.tzinfo is None else created_at
        )
        comparable_since = (
            since_dt.replace(tzinfo=UTC) if since_dt.tzinfo is None else since_dt
        )
        if comparable_created >= comparable_since:
            filtered.append(pr)
    return filtered


def fetch_pr_commits(
    owner: str,
    repo: str,
    number: int,
    *,
    token: str | None = None,
    base_url: str = GITHUB_API_URL,
) -> list[dict]:
    url = (
        f"{base_url.rstrip('/')}/repos/{quote(owner, safe='')}/"
        f"{quote(repo, safe='')}/pulls/{number}/commits"
    )
    return _paged_json(url, token=token, params={"per_page": 100})


def fetch_pr_diff(
    owner: str,
    repo: str,
    number: int,
    *,
    token: str | None = None,
    base_url: str = GITHUB_API_URL,
) -> str:
    url = (
        f"{base_url.rstrip('/')}/repos/{quote(owner, safe='')}/"
        f"{quote(repo, safe='')}/pulls/{number}"
    )
    return _get(url, token=token, accept="application/vnd.github.v3.diff").text
