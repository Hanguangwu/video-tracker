#!/usr/bin/env python3
"""跟踪源配置加载与平台抽象。

加载优先级：CHANNELS 环境变量（CI 的 GitHub Secret / 本地 .env）→ config/channels.json
格式：{"分组名": ["URL", ...]}
kind/platform 均为自动推断，无需手工标注。
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CHANNELS_FILE = ROOT / "config" / "channels.json"
LOCAL_ENV_FILE = ROOT / ".env"

# 平台注册表：后续扩展平台只需在此追加 host 特征
PLATFORMS = {
    "youtube": ["youtube.com", "youtu.be", "youtube-nocookie.com"],
    "bilibili": ["bilibili.com", "b23.tv"],
}


def _load_local_env() -> None:
    """轻量读取本地 .env（不覆盖已存在的环境变量，避免 Secret 优先级被本地文件盖掉）。"""
    if not LOCAL_ENV_FILE.exists():
        return
    for line in LOCAL_ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("\"'")
        os.environ.setdefault(key, value)


def load_channels() -> Dict[str, List[str]]:
    """返回 {"分组名": [URL...]}。CHANNELS env 优先，缺失读 config/channels.json。"""
    _load_local_env()
    raw = os.environ.get("CHANNELS")
    if raw and raw.strip():
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and data:
                return {str(k): [str(u) for u in v] for k, v in data.items()}
        except json.JSONDecodeError as exc:
            print(f"[warn] CHANNELS env 不是合法 JSON，回退配置文件: {exc}")
    if DEFAULT_CHANNELS_FILE.exists():
        return json.loads(DEFAULT_CHANNELS_FILE.read_text(encoding="utf-8"))
    raise SystemExit("未找到跟踪源：CHANNELS env 与 config/channels.json 均不可用")


def load_cookies() -> Optional[Path]:
    """COOKIES env 写入系统临时目录，返回路径（用完需删除）；未配置返回 None。"""
    raw = os.environ.get("COOKIES")
    if not raw:
        return None
    fd, path = tempfile.mkstemp(prefix="vt_cookies_", suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(raw)
    return Path(path)


def infer_platform(url: str) -> str:
    for platform, hosts in PLATFORMS.items():
        if any(h in url for h in hosts):
            return platform
    return "youtube"


def infer_kind(url: str) -> str:
    """URL → 模式。含 /videos、channel、playlist → 频道扫描；watch/bilibili 单视频 → video；裸 @频道默认按频道处理。"""
    lowered = url.lower()
    if any(k in lowered for k in ("/videos", "/channel/", "/playlist", "/video/")):
        return "channel"
    if "watch" in lowered or "video/" in lowered:
        return "video"
    return "channel"


@dataclass
class Source:
    group: str
    url: str
    platform: str
    kind: str


def iter_sources() -> List[Source]:
    """展开 channels 配置为 Source 列表（分组 × URL）。"""
    sources: List[Source] = []
    for group, urls in load_channels().items():
        for url in urls:
            url = url.strip()
            if not url:
                continue
            sources.append(
                Source(group=group, url=url, platform=infer_platform(url), kind=infer_kind(url))
            )
    if not sources:
        raise SystemExit("跟踪源配置为空")
    return sources