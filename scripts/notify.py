#!/usr/bin/env python3
"""通知适配器：钉钉 webhook / Server酱(微信)。

write_bot() 按环境变量装配已配置渠道，send_summary() 向全部渠道推送。
webhook/key 一律只从 env 读取，日志中绝不出现其值。
"""
from __future__ import annotations

import os
from typing import List

import requests


class DingTalkBot:
    def __init__(self, webhook: str) -> None:
        self.webhook = webhook

    def send(self, title: str, text: str) -> None:
        payload = {"msgtype": "markdown", "markdown": {"title": title, "text": text}}
        resp = requests.post(self.webhook, json=payload, timeout=15)
        resp.raise_for_status()


class ServerChanBot:
    def __init__(self, send_key: str) -> None:
        self.send_key = send_key

    def send(self, title: str, text: str) -> None:
        resp = requests.post(
            f"https://sctapi.ftqq.com/{self.send_key}.send",
            data={"title": title, "desp": text},
            timeout=15,
        )
        resp.raise_for_status()


def write_bot() -> List:
    """按 env 装配已配置的渠道，无则返回空列表。"""
    bots: List = []
    webhook = os.environ.get("DINGTALK_WEBHOOK")
    if webhook:
        bots.append(DingTalkBot(webhook))
    send_key = os.environ.get("SERVERCHAN_KEY")
    if send_key:
        bots.append(ServerChanBot(send_key))
    return bots


def send_summary(title: str, text: str, dry_run: bool = False) -> int:
    """向所有已配置渠道推送摘要，返回成功数；dry_run 仅打印并返回 0。"""
    bots = write_bot()
    if not bots or dry_run:
        print(f"[notify] {title}\n{text}")
        return 0
    ok = 0
    for bot in bots:
        try:
            bot.send(title, text)
            ok += 1
        except requests.RequestException as exc:
            print(f"[warn] 通知失败({type(bot).__name__}): {exc}")
    return ok