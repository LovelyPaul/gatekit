#!/usr/bin/env python3
"""build_manual_bundle — package docs/manual/ for import into Notion.

Notion's Markdown import turns one file into one page and a folder into a
parent page, so the archive is laid out as::

    <제목>.md          → the parent page's own body
    <제목>/*.md        → one child page per manual file, titled by its H1

Two details matter and are easy to get wrong by hand. The archive must set
the UTF-8 filename flag or Korean page titles arrive mangled, which the
``zip`` CLI does not do by default. And the parent body is a separate file
from the folder, or the tree comes in flat.

The repository stays the source of truth: edit docs/manual/, run this, and
re-import. Nothing here writes back into the manual.

    python3 tools/build_manual_bundle.py [--out PATH] [--title TITLE]
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import zipfile

DEFAULT_TITLE = "gatekit 사용자 매뉴얼"

PARENT_BODY = """# {title}

gatekit은 Claude Code 플러그인이다. `CLAUDE.md`에 산문으로 적던 규칙을 실제로
실행되는 훅으로 바꾼다.

이 매뉴얼은 {count}개 문서로 구성된다. 하위 페이지 목록은 이 페이지 아래에 있으며,
읽는 순서는 `00-index`에 정리되어 있다.

버전 {version} 기준이며, 모든 내용은 저장소의 `docs/ARCHITECTURE.md` 계약과 실제
코드에서 확인한 것만 담았다. 이 파일은 `tools/build_manual_bundle.py`가 생성한다 —
내용을 고칠 때는 저장소의 `docs/manual/`을 고치고 다시 생성한다.
"""


def plugin_version(root: pathlib.Path) -> str:
    import json
    manifest = root / "plugin" / ".claude-plugin" / "plugin.json"
    try:
        return json.loads(manifest.read_text(encoding="utf-8")).get("version", "0.0.0")
    except (OSError, ValueError):
        return "0.0.0"


def build(root: pathlib.Path, out: pathlib.Path, title: str) -> int:
    manual = root / "docs" / "manual"
    pages = sorted(manual.glob("*.md"))
    if not pages:
        print(f"no manual pages under {manual}", file=sys.stderr)
        return 1

    out.parent.mkdir(parents=True, exist_ok=True)
    body = PARENT_BODY.format(title=title, count=len(pages), version=plugin_version(root))

    # zipfile sets the language-encoding flag on every name it writes, so the
    # Korean folder and title survive the round trip.
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{title}.md", body)
        for page in pages:
            archive.write(page, f"{title}/{page.name}")

    print(f"{out}  ({len(pages)} child pages, {out.stat().st_size // 1024} KB)")
    print("import: Notion -> Import -> Markdown & CSV -> this file")
    return 0


def main(argv=None) -> int:
    # The default title is Korean; a cp1252 Windows console cannot print it.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=str(pathlib.Path(__file__).resolve().parent.parent))
    parser.add_argument("--out", default=None, help="output zip (default: dist/<title>.zip)")
    parser.add_argument("--title", default=DEFAULT_TITLE, help="parent page title")
    args = parser.parse_args(argv)
    root = pathlib.Path(args.root).resolve()
    out = pathlib.Path(args.out).expanduser() if args.out else root / "dist" / f"{args.title}.zip"
    return build(root, out, args.title)


if __name__ == "__main__":
    sys.exit(main())
