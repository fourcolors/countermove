"""Repository write seam used by the gate.

GateService depends only on RepoClient.  LocalRepoClient gives tests a real git
checkout with no network; GitHubRepoClient is the production adapter where the
GitHub credential and CLI invocation live.
"""

from __future__ import annotations

import os
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Mapping


class RepoClient(ABC):
    """Minimal command target for one branch-and-pull-request transaction."""

    @abstractmethod
    def create_branch(self, name: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def write_files(self, files: Mapping[str, str]) -> None:
        raise NotImplementedError

    @abstractmethod
    def open_pr(self, title: str, body: str) -> str:
        raise NotImplementedError


class LocalRepoClient(RepoClient):
    """A subprocess-git adapter for an existing plain local checkout."""

    def __init__(self, checkout_path: str | os.PathLike[str]):
        self.checkout_path = Path(checkout_path).resolve()
        self._branch: str | None = None
        self.opened_prs: list[dict[str, str]] = []
        self._base_branch = self._git("branch", "--show-current").stdout.strip()
        if not self._base_branch:
            raise ValueError("local checkout must be on a named branch")

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=self.checkout_path,
            check=True,
            text=True,
            capture_output=True,
        )

    def create_branch(self, name: str) -> None:
        if not name or name.startswith("-") or ".." in name:
            raise ValueError("invalid branch name")
        self._git("switch", self._base_branch)
        self._git("switch", "-c", name)
        self._branch = name

    def write_files(self, files: Mapping[str, str]) -> None:
        if self._branch is None:
            raise RuntimeError("create_branch must be called before write_files")
        root = self.checkout_path
        for relative, content in files.items():
            relative_path = Path(relative)
            if (
                relative_path.is_absolute()
                or not relative_path.parts
                or relative_path.parts[0] == ".git"
            ):
                raise ValueError(f"reserved repository path: {relative!r}")
            candidate = (root / relative).resolve()
            try:
                candidate.relative_to(root)
            except ValueError as exc:
                raise ValueError(f"file escapes checkout: {relative!r}") from exc
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.write_text(content, encoding="utf-8")

    def _commit(self, title: str) -> None:
        self._git("add", "--", "pricing.yaml", "decisions")
        self._git(
            "-c",
            "user.name=Countermove Gate",
            "-c",
            "user.email=gate@countermove.local",
            "commit",
            "-m",
            title,
        )

    def open_pr(self, title: str, body: str) -> str:
        if self._branch is None:
            raise RuntimeError("create_branch must be called before open_pr")
        self._commit(title)
        url = f"local://pull/{self._branch}"
        self.opened_prs.append(
            {"title": title, "body": body, "url": url, "branch": self._branch}
        )
        return url


class GitHubRepoClient(LocalRepoClient):
    """Production adapter: local git for content, ``gh`` for the remote PR.

    The checkout location, repository slug, and CLI binary are constructor
    seams so deployment can inject the credential-bearing environment.  Tests
    use LocalRepoClient and never construct or invoke this adapter.
    """

    def __init__(
        self,
        checkout_path: str | os.PathLike[str],
        repo_slug: str = "fourcolors/acme-stay-pricing",
        gh_binary: str = "gh",
    ):
        super().__init__(checkout_path)
        self.repo_slug = repo_slug
        self.gh_binary = gh_binary

    def open_pr(self, title: str, body: str) -> str:
        if self._branch is None:
            raise RuntimeError("create_branch must be called before open_pr")
        self._commit(title)
        self._git("push", "--set-upstream", "origin", self._branch)
        result = subprocess.run(
            [
                self.gh_binary,
                "pr",
                "create",
                "--repo",
                self.repo_slug,
                "--head",
                self._branch,
                "--title",
                title,
                "--body",
                body,
            ],
            cwd=self.checkout_path,
            check=True,
            text=True,
            capture_output=True,
        )
        return result.stdout.strip()
