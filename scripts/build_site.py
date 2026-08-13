#!/usr/bin/env python3
"""将 data/metadata/*.json 整理为可读静态站点（site/index.html），供 GitHub Pages 发布。

每个视频条目：标题（链接到原视频）+ 转录全文（若存在 data/transcripts/<id>.txt）。
排序：按 created_at（JSON 字段）倒序，缺省回退到文件 mtime，最新在前。

用法:
  python scripts/build_site.py            # 生成 site/index.html
"""
from __future__ import annotations

import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parent.parent
METADATA_DIR = ROOT / "data" / "metadata"
TRANSCRIPTS_DIR = ROOT / "data" / "transcripts"
OUT_DIR = ROOT / "site"
OUT_FILE = OUT_DIR / "index.html"

PAGE_TITLE = "视频跟踪存档"


def video_sort_key(meta: dict, path: Path) -> str:
    """优先用 JSON 里的时间戳；缺省回退到文件 mtime（ISO 字符串按字典序即时间序）。"""
    ts = meta.get("created_at") or meta.get("upload_date")
    if ts:
        return str(ts)
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def read_transcript(video_id: str) -> Optional[str]:
    f = TRANSCRIPTS_DIR / f"{video_id}.txt"
    if not f.exists():
        return None
    return f.read_text(encoding="utf-8").strip()


def render_video(meta: dict, transcript: Optional[str]) -> str:
    title = html.escape(str(meta.get("title") or meta.get("id") or "?"))
    url = html.escape(str(meta.get("url") or ""))
    link = f'<a href="{url}" target="_blank" rel="noopener">{title}</a>' if url else title

    if transcript:
        body = (
            '<details>\n'
            f'  <summary>转录全文（{len(transcript)} 字）</summary>\n'
            f'  <div class="transcript">{html.escape(transcript)}</div>\n'
            '</details>'
        )
    else:
        body = '<span class="no-sub">无可用字幕</span>'

    return (
        f'<article class="video">\n'
        f'  <h2>{link}</h2>\n'
        f'  {body}\n'
        '</article>'
    )


def build() -> int:
    if not METADATA_DIR.exists():
        print(f"[error] 未找到元数据目录: {METADATA_DIR}", file=sys.stderr)
        return 1

    entries: List[tuple] = []
    for path in sorted(METADATA_DIR.glob("*.json")):
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[warn] 跳过无法解析的元数据 {path.name}: {exc}")
            continue
        if not isinstance(meta, dict) or not meta.get("id"):
            print(f"[warn] 跳过缺少 id 的元数据 {path.name}")
            continue
        entries.append((meta, path))

    entries.sort(key=lambda e: video_sort_key(*e), reverse=True)

    now = datetime.now(timezone.utc)
    cards = "\n".join(render_video(meta, read_transcript(meta["id"])) for meta, _ in entries)

    page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(PAGE_TITLE)}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{
    font-family: system-ui, -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    max-width: 860px; margin: 0 auto; padding: 24px 16px 64px; line-height: 1.7;
  }}
  header h1 {{ font-size: 1.5rem; margin: 0 0 4px; }}
  .meta {{ color: #888; font-size: .9rem; margin-bottom: 24px; }}
  .video {{
    border: 1px solid #4444; border-radius: 8px; padding: 12px 16px; margin-bottom: 12px;
    background: #fff1;
  }}
  .video h2 {{ font-size: 1rem; margin: 0 0 6px; }}
  .video h2 a {{ color: inherit; text-decoration: none; }}
  .video h2 a:hover {{ text-decoration: underline; }}
  details summary {{ cursor: pointer; font-size: .9rem; color: #666; user-select: none; }}
  .transcript {{
    white-space: pre-wrap; word-break: break-word; font-size: .95rem;
    margin-top: 10px; padding-top: 10px; border-top: 1px dashed #4444;
  }}
  .no-sub {{ color: #999; font-style: italic; font-size: .9rem; }}
  footer {{ margin-top: 32px; font-size: .85rem; color: #999; }}
</style>
</head>
<body>
<header>
  <h1>{html.escape(PAGE_TITLE)}</h1>
  <div class="meta">共 {len(entries)} 条 · 生成于 {now:%Y-%m-%d %H:%M} UTC</div>
</header>
<main>
{cards}
</main>
<footer>由 video-tracker 自动生成 · 数据源 data/metadata</footer>
</body>
</html>
"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(page, encoding="utf-8")
    print(f"[ok] 已生成 {OUT_FILE}（{len(entries)} 条）")
    return 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    return build()


if __name__ == "__main__":
    sys.exit(main())
