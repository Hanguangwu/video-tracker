#!/usr/bin/env python3
"""模式 A 主流程编排：探测 → 转录 → Email → 通知 → 入库。

用法:
  python scripts/track.py            # 正常跑（发送邮件/通知）
  python scripts/track.py --dry-run  # 只打印不发送
  python scripts/track.py --source "分组名"  # 只处理指定分组
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from sources import iter_sources, load_cookies
from transcript import extract_plain_text

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TRANSCRIPTS_DIR = DATA / "transcripts"
METADATA_DIR = DATA / "metadata"
SEEN_FILE = DATA / "seen.txt"
SKIPPED_FILE = DATA / "skipped.txt"
REPORT_FILE = ROOT / "report.json"

PLAYLIST_END = 20          # 频道扫描条数上限
PROBE_TIMEOUT = 180        # 探测单源超时（秒）
SUBTITLE_TIMEOUT = 300     # 单视频字幕超时（秒）
MIN_INTERVAL = 2           # yt-dlp 请求间隔下限/上限/重试
MAX_INTERVAL = 5
RETRIES = 3

SKIP_CATEGORIES = ("members_only", "needs_auth", "unavailable")


def classify_subtitle_error(combined: str) -> Optional[str]:
    """按 yt-dlp 错误特征归类可预测的跳过原因；无法归类返回 None（视为真失败）。"""
    low = combined.lower()
    if "members-only" in low or "join this channel to get access" in low:
        return "members_only"
    if ("not a bot" in low or "from-browser or --cookies" in low
            or "login to download" in low or "please sign in" in low or "must be logged in" in low):
        return "needs_auth"
    if ("unavailable" in low or "not available" in low or "private" in low
            or "has been removed" in low or "does not exist" in low):
        return "unavailable"
    return None


def load_seen() -> set:
    if not SEEN_FILE.exists():
        return set()
    return {ln.strip() for ln in SEEN_FILE.read_text(encoding="utf-8").splitlines() if ln.strip()}


def append_seen(video_ids: List[str]) -> None:
    if not video_ids:
        return
    DATA.mkdir(parents=True, exist_ok=True)
    existing = load_seen()
    with open(SEEN_FILE, "a", encoding="utf-8") as fh:
        for vid in video_ids:
            if vid not in existing:
                fh.write(vid + "\n")


def load_skipped() -> Dict[str, str]:
    """返回 {video_id: category}。skipped.txt 与 seen.txt 独立：删除它可在补 cookies 后重试。"""
    if not SKIPPED_FILE.exists():
        return {}
    out: Dict[str, str] = {}
    for ln in SKIPPED_FILE.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln:
            vid, _, cat = ln.partition("\t")
            if vid:
                out[vid.strip()] = cat.strip()
    return out


def append_skipped(entries: Dict[str, str]) -> None:
    if not entries:
        return
    DATA.mkdir(parents=True, exist_ok=True)
    existing = load_skipped()
    with open(SKIPPED_FILE, "a", encoding="utf-8") as fh:
        for vid, cat in entries.items():
            if vid not in existing:
                fh.write(f"{vid}\t{cat}\n")


def build_ytdlp_base(cookie_path: Optional[Path]) -> List[str]:
    """公共 yt-dlp 参数：请求间隔 + 重试 + 可选 cookies。"""
    args = [
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
    return args


def decode_output(raw: bytes) -> str:
    """yt-dlp 管道输出解码：Linux CI 为 UTF-8；Windows 控制台环境常为 GBK。按字节特征选择。"""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("gbk", errors="replace")


def probe_channel(url: str, cookie_path: Optional[Path]) -> List[Dict]:
    """取源最近 N 条视频（--flat-playlist 轻量模式，不下载）。"""
    cmd = (
        ["yt-dlp", "--flat-playlist", "--playlist-end", str(PLAYLIST_END),
         "--print", "%(id)s\t%(title)s\t%(webpage_url)s"]
        + build_ytdlp_base(cookie_path) + [url]
    )
    result = subprocess.run(cmd, capture_output=True, timeout=PROBE_TIMEOUT)
    stdout = decode_output(result.stdout)
    if result.returncode != 0 and not stdout.strip():
        print(f"[warn] 探测失败 <{url}>: {decode_output(result.stderr)[-200:]}")
    videos: List[Dict] = []
    for line in stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3 or not parts[0]:
            continue
        videos.append({"id": parts[0], "title": parts[1], "url": parts[2]})
    return videos


def fetch_subtitles(url: str, video_id: str, cookie_path: Optional[Path]) -> str:
    """下载视频字幕文件（不下载视频本体）。

    返回状态：ok / members_only / needs_auth / unavailable / error。
    可预测的跳过原因（会员专属/需登录/不可用）不判定为失败，避免误报。
    """
    cmd = (
        ["yt-dlp", "--skip-download", "--write-subs", "--write-auto-subs",
         "--sub-langs", "zh-Hant,zh-Hans,en", "--sub-format", "vtt",
         "--output", str(TRANSCRIPTS_DIR / video_id)]
        + build_ytdlp_base(cookie_path) + [url]
    )
    result = subprocess.run(cmd, capture_output=True, timeout=SUBTITLE_TIMEOUT)
    combined = (decode_output(result.stdout) + decode_output(result.stderr)).lower()
    if "has already been downloaded" in combined or "has already been recorded" in combined:
        return "ok"
    if result.returncode != 0:
        skip = classify_subtitle_error(combined)
        if skip:
            print(f"[skip] <{video_id}> {skip}: {combined[-200:]}")
            return skip
        print(f"[warn] 字幕获取失败 <{video_id}>: {combined[-300:]}")
        return "error"
    return "ok"


def save_metadata(video: Dict) -> None:
    METADATA_DIR.mkdir(parents=True, exist_ok=True)
    path = METADATA_DIR / f"{video['id']}.json"
    data = {**video, "created_at": datetime.now(timezone.utc).isoformat()}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def cleanup_subtitle_files(video_id: str) -> None:
    """转录入库后清理原始 .vtt/.srt，避免散落（保留已解析的 .txt）。"""
    for pattern in (f"{video_id}.*.vtt", f"{video_id}.*.srt", f"{video_id}.vtt", f"{video_id}.srt"):
        for f in TRANSCRIPTS_DIR.glob(pattern):
            f.unlink(missing_ok=True)


def process_video(video: Dict, cookie_path: Optional[Path]) -> tuple:
    """对单个新视频抓字幕并转纯文本，返回 (转录文本, 状态)。无字幕时文本为 None。"""
    save_metadata(video)
    status = fetch_subtitles(video["url"], video["id"], cookie_path)
    if status != "ok":
        return None, status
    text = extract_plain_text(TRANSCRIPTS_DIR, video["id"])
    if text:
        (TRANSCRIPTS_DIR / f"{video['id']}.txt").write_text(text, encoding="utf-8")
    cleanup_subtitle_files(video["id"])
    return text, "ok"


def summarize(dry_run: bool, source_filter: Optional[str] = None) -> int:
    """主流程，返回新增视频数。source_filter 指定只处理的分组名。"""
    from emailer import send_transcript_email
    from notify import send_summary

    seen = load_seen()
    skipped = load_skipped()
    processed = set(seen) | set(skipped)
    cookie_path = load_cookies()
    new_videos: List[Dict] = []
    skipped_now: Dict[str, str] = {}
    report: Dict = {
        "date": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "sources": [],
    }
    try:
        for src in iter_sources():
            if source_filter and src.group != source_filter:
                continue
            videos = probe_channel(src.url, cookie_path)
            fresh = [v for v in videos if v["id"] not in processed]
            src_report = {"group": src.group, "url": src.url, "kind": src.kind, "new": len(fresh)}
            print(f"[probe] {src.group} → 扫描 {len(videos)} 条，新视频 {len(fresh)} 个")
            saved: List[str] = []
            no_subtitle: List[str] = []
            src_skipped: Dict[str, str] = {}
            for video in fresh:
                text, status = process_video(video, cookie_path)
                if status in SKIP_CATEGORIES:
                    print(f"[probe] {src.group} 跳过 <{video['id']}>: {status}")
                    src_skipped[video["id"]] = status
                    continue
                transcript_file = (
                    TRANSCRIPTS_DIR / f"{video['id']}.txt"
                    if text else None
                )
                new_videos.append({**video, "transcript": text, "file": str(transcript_file) if transcript_file else None})
                if transcript_file:
                    saved.append(video["id"])
                else:
                    no_subtitle.append(video["id"])
                try:
                    send_transcript_email(video["title"], video["url"], text, dry_run=dry_run)
                except Exception as exc:
                    print(f"[warn] 邮件发送失败 <{video['id']}>: {exc}")
            src_report["saved"] = saved
            src_report["no_subtitle"] = no_subtitle
            if src_skipped:
                src_report["skipped"] = dict(src_skipped)
            skipped_now.update(src_skipped)
            report["sources"].append(src_report)

        if new_videos:
            title = f"视频更新 {len(new_videos)} 个 {datetime.now(timezone.utc):%m-%d %H:%M}"
            lines = [f"- [{v['title']}]({v['url']})" + ("" if v["file"] else "（无可用字幕）") for v in new_videos]
            if skipped_now:
                lines.append("")
                lines.append(f"跳过 {len(skipped_now)} 个（会员专属/需登录/不可用）: " + ", ".join(skipped_now))
            try:
                send_summary(title, "\n".join(lines), dry_run=dry_run)
            except Exception as exc:
                print(f"[warn] 通知失败: {exc}")

        if not dry_run:
            append_seen([v["id"] for v in new_videos])
            append_skipped(skipped_now)
        report["new_videos"] = len(new_videos)
        report["new_ids"] = [v["id"] for v in new_videos]
    finally:
        if cookie_path:
            cookie_path.unlink(missing_ok=True)
    REPORT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(new_videos)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    parser = argparse.ArgumentParser(description="视频跟踪：探测→转录→Email→通知→入库")
    parser.add_argument("--dry-run", action="store_true", help="不发送邮件/通知且不写 seen.txt")
    parser.add_argument("--source", help="只处理指定分组名")
    args = parser.parse_args()

    if args.source:
        groups = {s.group for s in iter_sources()}
        if args.source not in groups:
            print(f"[error] 分组不存在: {args.source}（可用: {', '.join(sorted(groups))}）")
            return 1
    summarize(args.dry_run, args.source)
    return 0


if __name__ == "__main__":
    sys.exit(main())