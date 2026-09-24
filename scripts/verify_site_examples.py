"""Execute the Python examples marked for verification on the public site."""

from __future__ import annotations

import html
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path


class _ExampleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.examples: list[str] = []
        self._depth = 0
        self._current: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "pre" and attributes.get("data-verify") == "python":
            self._current = []
            self._depth = 1
            return
        if self._current is not None:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._current is None:
            return
        if tag == "pre" and self._depth == 1:
            self.examples.append(html.unescape("".join(self._current)))
            self._current = None
            self._depth = 0
            return
        self._depth -= 1

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._current.append(data)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    dist = root / "site" / "dist"
    pages = sorted(dist.rglob("*.html"))
    parser = _ExampleParser()
    for page in pages:
        parser.feed(page.read_text(encoding="utf-8"))

    if not parser.examples:
        raise SystemExit("no data-verify=python examples found in site/dist")

    for index, example in enumerate(parser.examples, start=1):
        subprocess.run(
            [sys.executable, "-c", example],
            cwd=root,
            check=True,
            timeout=20,
        )
        print(f"verified site Python example {index}")


if __name__ == "__main__":
    main()
