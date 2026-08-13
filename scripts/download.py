#!/usr/bin/env python3
"""模式 B：按需下载视频到 data/downloads/，产出文件清单 manifest.json。

用法:
  python scripts/download.py --source "文昭 Wen Zhao 频道"   # 下载指定分组
  python scripts/download.py --video-url https://www.youtube.com/watch?v=...  # 单个视频
  python scripts/download.py                                  # 全部分组
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from sources import iter_sources, load_cookies

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_FILE = ROOT / "archive.txt"
DOWNLOADS_DIR = ROOT / "data" / "downloads"
MANIFEST_FILE = DOWNLOADS_DIR / "manifest.json"

DOWNLOAD_TIMEOUT = 1200
MIN_INTERVAL = 2
MAX_INTERVAL = 5
RETRIES = 3
FORMAT_SPEC = "bestvideo[height<=1080]+bestaudio/best[height<=1080]"
OUTPUT_TEMPLATE = "%(upload_date)s - %(title).100s.%(ext)s"


def build_ytdlp_args(cookie_path: Optional[Path], urls: List[str], dry_run: bool) -> List[str]:
    args = [
        "yt-dlp",
        "--download-archive", str(ARCHIVE_FILE),
        "--no-overwrites",
        "--write-info-json",
        "--format", FORMAT_SPEC,
        "--merge-output-format", "mp4",
        "--output", str(DOWNLOADS_DIR / OUTPUT_TEMPLATE),
        "--sleep-interval", str(MIN_INTERVAL),
        "--max-sleep-interval", str(MAX_INTERVAL),
        "--retries", str(RETRIES),
        "--no-warnings",
    ]
    js_runtimes = os.environ.get("YTDLP_JS_RUNTIMES")
    if js_runtimes:
        args += ["--js-runtimes", js_runtimes]
    extractor_args = os.environ.get("YTDLP_EXTRACTOR_ARGS")
    if extractor_args:
        args += ["--extractor-args", extractor_args]
    if cookie_path:
        args += ["--cookies", str(cookie_path)]
    if dry_run:
        args += ["--simulate"]
    args += urls
    return args


def collect_manifest(dry_run: bool) -> dict:
    """扫描下载目录，生成 {files:[{name,size_mb}], total, total_size_mb}。"""
    if not DOWNLOADS_DIR.exists():
        return {"files": [], "total": 0, "total_size_mb": 0.0}
    entries = []
    for path in DOWNLOADS_DIR.glob("*.mp4"):
        if dry_run or path.name == "manifest.json":
            continue
        entries.append({"name": path.name, "size_mb": round(path.stat().st_size / 1024 / 1024, 1)})
    entries.sort(key=lambda e: e["name"])
    manifest = {
        "files": entries,
        "total": len(entries),
        "total_size_mb": round(sum(e["size_mb"] for e in entries), 1),
    }
    MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_FILE.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def run_downloads(urls: List[str], dry_run: bool) -> int:
    cookie_path = load_cookies()
    try:
        cmd = build_ytdlp_args(cookie_path, urls, dry_run)
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=DOWNLOAD_TIMEOUT)
        combined = (result.stdout + result.stderr)
        if "has already been downloaded" in combined.lower() or "has already been recorded" in combined.lower():
            print("[info] 全部已在 archive，跳过下载")
        elif result.returncode != 0:
            print(f"[warn] yt-dlp 退出码 {result.returncode}（部分重试/跳过属正常）: {combined[-500:]}")
        manifest = collect_manifest(dry_run)
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return result.returncode
    finally:
        if cookie_path:
            cookie_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="模式 B：yt-dlp 下载视频到 data/downloads")
    parser.add_argument("--source", help="分组名（缺省=全部分组）")
    parser.add_argument("--video-url", help="单个视频 URL")
    parser.add_argument("--dry-run", action="store_true", help="只模拟，不真下载")
    args = parser.parse_args()

    target = args.video_url
    if target:
        urls = [target]
    else:
        urls = [s.url for s in iter_sources() if not args.source or s.group == args.source]
        if not urls:
            print(f"[error] 分组不存在或无 URL: {args.source}")
            return 1
    print(f"待处理 {len(urls)} 个 URL: {urls}")
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    return run_downloads(urls, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())