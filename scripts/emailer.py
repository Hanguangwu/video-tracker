#!/usr/bin/env python3
"""SMTP 邮件发送（QQ 邮箱 465 SSL 默认），每个新视频一封。"""
from __future__ import annotations

import os
import smtplib
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Optional

DEFAULT_HOST = "smtp.qq.com"
DEFAULT_PORT = 465
MAX_BODY_CHARS = 50000  # 单封邮件正文上限，防止超长转录撑爆邮件


def _require_email(name: str, value: str) -> str:
    """校验并返回完整邮箱地址。QQ SMTP 的 envelope 发件人必须是裸完整邮箱（不能带显示名）。"""
    value = value.strip()
    if "@" not in value or value.startswith("@") or value.endswith("@"):
        raise ValueError(f"{name} 必须是完整邮箱地址（含 @ 域名，如 xxx@qq.com），当前值: {value!r}")
    return value


def send_transcript_email(
    video_title: str,
    video_url: str,
    transcript_text: Optional[str],
    dry_run: bool = False,
) -> bool:
    """发送一封含链接+转录全文的邮件。dry_run 仅打印不发送且不读 SMTP 配置。"""
    if transcript_text:
        body = f"视频链接: {video_url}\n\n{transcript_text}"[:MAX_BODY_CHARS]
    else:
        body = f"视频链接: {video_url}\n\n无可用字幕"

    subject = f"[视频跟踪] {video_title}"
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")

    if dry_run:
        print(f"[mail dry-run] 标题={subject}")
        print(body[:800])
        return True

    smtp_host = os.environ.get("SMTP_HOST", DEFAULT_HOST)
    smtp_port = int(os.environ.get("SMTP_PORT", str(DEFAULT_PORT)))
    smtp_user = _require_email("SMTP_USER", os.environ["SMTP_USER"])
    smtp_pass = os.environ["SMTP_PASS"]
    mail_to = _require_email("MAIL_TO", os.environ["MAIL_TO"])
    mail_from = _require_email("MAIL_FROM", os.environ.get("MAIL_FROM", smtp_user))
    msg["From"] = formataddr(("video-tracker", mail_from))
    msg["To"] = mail_to

    if smtp_port == 465:
        server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30)
    else:
        server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
        server.starttls()
    try:
        server.login(smtp_user, smtp_pass)
        # envelope（MAIL FROM/RCPT TO）显式指定：QQ 要求 MAIL FROM 与登录账号一致，
        # 且必须是裸邮箱地址。默认 send_message 会从 From 头取 envelope，
        # 而 formataddr 生成的 "视频跟踪 <a@b.c>" 带显示名，会触发 502 Invalid paramenters。
        server.send_message(msg, from_addr=smtp_user, to_addrs=[mail_to])
        print(f"[mail] 已发送: {video_title}")
        return True
    finally:
        server.quit()