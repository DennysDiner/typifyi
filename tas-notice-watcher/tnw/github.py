"""A minimal GitHub Issues client (§2.5).

GitHub Issues is the alerting channel and the triage queue. Only three
operations are needed: create an issue, comment on one, and find open issues
carrying one of our fingerprints so that a recurring failure updates a thread
instead of spamming a new one every run.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import quote

import requests

LOG = logging.getLogger(__name__)
API_ROOT = "https://api.github.com"


@dataclass
class IssueRef:
    number: int
    url: str
    title: str = ""
    body: str = ""


class IssueClient(Protocol):
    def create_issue(self, title: str, body: str, labels: list[str]) -> IssueRef: ...
    def comment(self, number: int, body: str) -> None: ...
    def find_open_issue(self, label: str, fingerprint: str) -> IssueRef | None: ...
    def ensure_labels(self, labels: list[str]) -> None: ...


class GitHubIssueClient:
    def __init__(
        self,
        repository: str | None = None,
        token: str | None = None,
        *,
        session: requests.Session | None = None,
        api_root: str = API_ROOT,
        timeout_s: float = 30.0,
    ) -> None:
        self.repository = repository or os.environ.get("GITHUB_REPOSITORY", "")
        self.token = token or os.environ.get("GITHUB_TOKEN", "")
        if not self.repository:
            raise ValueError("GITHUB_REPOSITORY is not set")
        if not self.token:
            raise ValueError("GITHUB_TOKEN is not set")
        self.session = session or requests.Session()
        self.api_root = api_root.rstrip("/")
        self.timeout_s = timeout_s

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "tas-notice-watcher",
        }

    def _request(self, method: str, path: str, payload: dict | None = None) -> Any:
        url = f"{self.api_root}{path}"
        response = self.session.request(
            method,
            url,
            headers=self._headers,
            data=json.dumps(payload) if payload is not None else None,
            timeout=self.timeout_s,
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"GitHub API {method} {path} failed: {response.status_code} {response.text[:400]}"
            )
        return response.json() if response.content else {}

    def create_issue(self, title: str, body: str, labels: list[str]) -> IssueRef:
        data = self._request(
            "POST",
            f"/repos/{self.repository}/issues",
            {"title": title[:250], "body": body, "labels": labels},
        )
        return IssueRef(number=data["number"], url=data["html_url"], title=title, body=body)

    def comment(self, number: int, body: str) -> None:
        self._request("POST", f"/repos/{self.repository}/issues/{number}/comments", {"body": body})

    def find_open_issue(self, label: str, fingerprint: str) -> IssueRef | None:
        path = (
            f"/repos/{self.repository}/issues?state=open&per_page=50&labels={quote(label)}"
        )
        for issue in self._request("GET", path) or []:
            if fingerprint in (issue.get("body") or ""):
                return IssueRef(
                    number=issue["number"],
                    url=issue["html_url"],
                    title=issue.get("title", ""),
                    body=issue.get("body", ""),
                )
        return None

    def ensure_labels(self, labels: list[str]) -> None:
        """Create any missing labels; harmless if they already exist."""
        for label in labels:
            try:
                self._request("GET", f"/repos/{self.repository}/labels/{quote(label)}")
            except RuntimeError:
                try:
                    self._request(
                        "POST",
                        f"/repos/{self.repository}/labels",
                        {"name": label, "color": _label_colour(label),
                         "description": "tas-notice-watcher"},
                    )
                except RuntimeError as exc:  # a race, or insufficient permissions
                    LOG.warning("could not create label %s: %s", label, exc)


def _label_colour(label: str) -> str:
    if "failure" in label:
        return "b60205"
    if "priority:1" in label:
        return "d93f0b"
    if label.startswith("tnw:source:"):
        return "0e8a16"
    return "1d76db"


@dataclass
class DryRunIssueClient:
    """Records what would have been posted. Used by ``--dry-run`` and by tests."""

    created: list[IssueRef] = field(default_factory=list)
    comments: list[tuple[int, str]] = field(default_factory=list)
    existing: list[IssueRef] = field(default_factory=list)
    labels_ensured: list[str] = field(default_factory=list)

    def create_issue(self, title: str, body: str, labels: list[str]) -> IssueRef:
        ref = IssueRef(number=len(self.created) + 1, url="dry-run://issue", title=title, body=body)
        self.created.append(ref)
        return ref

    def comment(self, number: int, body: str) -> None:
        self.comments.append((number, body))

    def find_open_issue(self, label: str, fingerprint: str) -> IssueRef | None:
        for issue in self.existing:
            if fingerprint in issue.body:
                return issue
        return None

    def ensure_labels(self, labels: list[str]) -> None:
        self.labels_ensured.extend(labels)
