"""System prompt as ordered, named sections. A section is a string or a zero-argument callable evaluated at
render time, so live content (agent notes, budget left, current plan state) is refreshed every turn."""
from __future__ import annotations

from typing import Callable, Union

Content = Union[str, Callable[[], str]]


class PromptBuilder:
    def __init__(self) -> None:
        self._sections: list[tuple[str, Content]] = []

    def _index(self, name: str) -> int:
        for i, (n, _) in enumerate(self._sections):
            if n == name:
                return i
        raise KeyError(f"no prompt section {name!r}; sections: {self.names()}")

    def set(self, name: str, content: Content, *, before: str | None = None, after: str | None = None) -> None:
        """Replace `name` in place if it exists; otherwise insert before/after an anchor, or append."""
        if any(n == name for n, _ in self._sections):
            self._sections[self._index(name)] = (name, content)
        elif before is not None:
            self._sections.insert(self._index(before), (name, content))
        elif after is not None:
            self._sections.insert(self._index(after) + 1, (name, content))
        else:
            self._sections.append((name, content))

    def remove(self, name: str) -> None:
        del self._sections[self._index(name)]

    def names(self) -> list[str]:
        return [n for n, _ in self._sections]

    def render(self) -> str:
        parts = []
        for _, content in self._sections:
            text = content() if callable(content) else content
            if text and text.strip():
                parts.append(text)
        return "\n\n".join(parts)

    def copy(self) -> PromptBuilder:
        other = PromptBuilder()
        other._sections = list(self._sections)
        return other
