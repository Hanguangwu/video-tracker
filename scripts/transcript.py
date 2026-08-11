#!/usr/bin/env python3
"""vtt/srt 字幕 → 纯文本。

yt-dlp --sub-format vtt 下载的字幕文件形如 <base>.<lang>.vtt。
按语言优先级 zh-Hant → zh-Hans → en 挑选最佳文件，解析为纯文本。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

# 语言优先级：zh-Hant 首选 → zh-Hans → en
LANG_PRIORITY = ["zh-Hant", "zh-Hans", "en"]

# 常见语言码别名 → 归一化语言（YouTube 自动字幕可能给 zh-Hans/zh-Hant/zh-CN/zh-TW 等）
LANG_ALIASES = {
    "zh-hant": "zh-Hant", "zh-tw": "zh-Hant", "zh-cht": "zh-Hant", "cht": "zh-Hant",
    "zh-hans": "zh-Hans", "zh-cn": "zh-Hans", "zh-chs": "zh-Hans", "chs": "zh-Hans",
    "en": "en", "en-us": "en", "en-orig": "en",
}

# WEBVTT 头：WEBVTT / Kind: / Language: / NOTE / STYLE / REGION 行
_VTT_HEADER = re.compile(r"^(WEBVTT|Kind:|Language:|NOTE|STYLE|REGION)(\s|$)", re.IGNORECASE)
# 序号行：纯整数
_CUE_INDEX = re.compile(r"^\d+$")
# 时间轴行：00:00:01.000 --> 00:00:04.000（vtt 用 .，srt 用 ,）
_TIMESTAMP = re.compile(
    r"^\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}"
)
# 行内标签：<c>、<00:00:02.000>、<v 说话人> 等
_INLINE_TAG = re.compile(r"<[^>]+>")


def _normalize_lang(filename: str) -> Optional[str]:
    """从字幕文件名提取语言码 → 归一化；识别不了返回 None。"""
    stem = Path(filename).stem  # 如 vid.zh-Hant
    parts = stem.split(".")[-2:]  # 语言码通常在最后一段
    for part in reversed(parts):
        key = part.lower()
        if key in LANG_ALIASES:
            return LANG_ALIASES[key]
    return None


def pick_best_subtitle(transcript_dir: Path, video_id: str) -> Optional[Path]:
    """在字幕文件中按语言优先级选择最佳 .vtt/.srt，找不到返回 None。"""
    candidates: List[Path] = []
    for pattern in (f"{video_id}.*", f"*-{video_id}.*"):
        candidates.extend(transcript_dir.glob(pattern))
    # 过滤掉已生成的 .txt 等，只留字幕文件
    candidates = [p for p in candidates if p.suffix.lower() in (".vtt", ".srt")]
    if not candidates:
        return None
    ranked = []
    for path in candidates:
        lang = _normalize_lang(path.name)
        priority = LANG_PRIORITY.index(lang) if lang in LANG_PRIORITY else len(LANG_PRIORITY)
        ranked.append((priority, lang or "", path))
    ranked.sort(key=lambda x: (x[0], x[1]))
    return ranked[0][2]


def _strip_inline(line: str) -> str:
    """去掉行内标签与多余空白，兼容 vtt 自动字幕的 <00:00:02.000> 时间戳。"""
    line = _INLINE_TAG.sub(" ", line)
    # HTML 实体还原（自动字幕偶见 &amp; 等）
    line = line.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", line).strip()


def parse_subtitle_file(path: Path) -> str:
    """解析单个 vtt/srt 文件为纯文本。"""
    content = path.read_text(encoding="utf-8-sig", errors="replace")
    lines = content.splitlines()
    text_parts: List[str] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if _VTT_HEADER.match(line):
            continue  # WEBVTT/Kind/Language/NOTE 头
        if _CUE_INDEX.match(line):
            continue  # 字幕序号
        if _TIMESTAMP.search(line):
            continue  # 时间轴
        cleaned = _strip_inline(line)
        if cleaned and cleaned not in text_parts[-1:]:
            text_parts.append(cleaned)
    return "\n".join(text_parts)


def extract_plain_text(transcript_dir: Path, video_id: str) -> Optional[str]:
    """按语言优先级挑选字幕并转纯文本；无字幕返回 None。"""
    best = pick_best_subtitle(transcript_dir, video_id)
    if best is None:
        return None
    return parse_subtitle_file(best)