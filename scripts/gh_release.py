#!/usr/bin/env python3
"""上传文件到 GitHub Releases 并返回下载链接。

用法:
  python scripts/gh_release.py --dir data/downloads   # 上传目录下所有 *.mp4
  python scripts/gh_release.py --file a.mp4 --file b.mp4
依赖: GITHUB_TOKEN / GITHUB_REPOSITORY 环境变量（Actions 自动注入）
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import requests

API = "https://api.github.com"


def upload_assets(repo: str, token: str, files: List[Path], dry_run: bool) -> List[str]:
    tag = f"videos-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    if dry_run:
        print(f"[dry-run] 将创建 release tag={tag} 并上传 {len(files)} 个文件")
        for f in files:
            print(f"[dry-run]   {f.name} ({f.stat().st_size / 1024 / 1024:.1f} MB)")
        return [f"https://example.invalid/{tag}/{f.name}" for f in files]

    resp = requests.post(
        f"{API}/repos/{repo}/releases",
        headers=headers,
        json={"tag_name": tag, "name": f"视频下载 {datetime.now(timezone.utc):%Y-%m-%d %H:%M}", "generate_release_notes": False},
        timeout=30,
    )
    resp.raise_for_status()
    release = resp.json()
    upload_url = release["upload_url"].split("{")[0]
    links: List[str] = []
    for f in files:
        mime = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        with open(f, "rb") as fh:
            up = requests.post(
                upload_url,
                headers={**headers, "Content-Type": mime},
                params={"name": f.name},
                data=fh,
                timeout=1800,
            )
        up.raise_for_status()
        asset = up.json()
        links.append(asset.get("browser_download_url", f"asset:{asset['name']}"))
        print(f"[release] 已上传: {asset['name']} → {links[-1]}")
    return links


def main() -> int:
    parser = argparse.ArgumentParser(description="上传文件到 GitHub Releases")
    parser.add_argument("--dir", help="扫描目录（上传其中所有 *.mp4）")
    parser.add_argument("--file", action="append", default=[], help="指定文件（可多次）")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        print("[error] 缺少 GITHUB_TOKEN 或 GITHUB_REPOSITORY 环境变量")
        return 1

    files: List[Path] = [Path(p) for p in args.file]
    if args.dir:
        files += sorted(Path(args.dir).glob("*.mp4"))
    files = sorted({f.resolve() for f in files if f.exists()})
    if not files:
        print("[info] 没有可上传的文件（已全部下载过或被过滤）")
        return 0
    upload_assets(repo, token, files, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())