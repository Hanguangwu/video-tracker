# video-tracker

基于 GitHub Actions 免费的 **视频跟踪/转录管线**：定时监控 YouTube 频道更新 → 提取转录文本 → Email 推送 + 钉钉/微信通知。默认不下载视频；需要时手动触发下载并存到 GitHub Releases。

## 功能

- **模式 A（默认，定时）**：cron 每 6 小时扫描配置的频道 → 新视频自动抓 YouTube 字幕 → 转录为纯文本 → **Email 一次一封** + **钉钉/微信摘要通知**
- **模式 B（手动）**：手动触发下载视频（最高 1080p mp4）→ 上传 GitHub Releases → 通知附下载链接
- 去重：`data/seen.txt`（转录）+ `archive.txt`（真下载），两套互不干扰
- 无新视频时不发邮件/通知，不打扰
- 预留 Bilibili 支持（yt-dlp 原生；配置按 URL 自动识别平台）

## 目录结构

```
.github/workflows/
  track.yml          # 模式 A：定时监控主流程
  download.yml       # 模式 B：手动下载 → Releases
config/
  channels.json      # 默认跟踪源（非敏感，入库）
scripts/
  track.py           # 模式 A 编排
  sources.py         # 加载 CHANNELS env / channels.json + 平台抽象
  transcript.py      # vtt/srt → 纯文本，zh-Hant→zh-Hans→en 优先
  notify.py          # 钉钉 / Server酱 适配器
  emailer.py         # SMTP 发送转录（QQ 邮箱授权码）
  download.py        # 模式 B 下载
  gh_release.py      # 上传 GitHub Releases
archive.txt          # yt-dlp 下载去重（入库）
data/
  seen.txt           # 转录去重（入库）
  transcripts/       # 转录文本（入库）
  metadata/          # 视频元数据（入库）
  downloads/         # 视频文件（.gitignore，不入库）
```

## 快速开始

### 1. 本地试跑（不真发送）

```bash
pip install -r requirements.txt
python scripts/track.py --dry-run     # 只打印探测/转录/邮件内容，不发送、不写 seen.txt
python scripts/track.py --source "文昭 Wen Zhao 频道" --dry-run
```

### 2. 配置跟踪源

改 `config/channels.json`（入库，非敏感）：

```json
{
  "分组名": ["https://www.youtube.com/@频道/videos", "https://www.youtube.com/watch?v=xxx"]
}
```

- URL 含 `@频道/videos`/`channel`/`playlist` → 按频道扫描最近 20 条
- URL 含 `watch?v=` → 单视频处理一次
- CI 中也可用 GitHub Secret `CHANNELS` 整体覆盖（内容与文件同格式）

### 3. 配置 GitHub Secrets

仓库 → Settings → Secrets and variables → Actions → New repository secret：

| Secret | 说明 | 必需 |
|---|---|---|
| `SMTP_HOST` / `SMTP_PORT` | QQ 邮箱：`smtp.qq.com` / `465` | Email 必需 |
| `SMTP_USER` / `SMTP_PASS` | 发信 QQ 邮箱 + **授权码**（非登录密码） | Email 必需 |
| `MAIL_TO` | 收件人邮箱 | Email 必需 |
| `MAIL_FROM` | 发件人（默认=SMTP_USER，可省略） | 否 |
| `DINGTALK_WEBHOOK` | 钉钉机器人 webhook | 通知可选 |
| `SERVERCHAN_KEY` | Server酱 SendKey（微信推送） | 通知可选 |
| `COOKIES` | Netscape 格式 Cookie（登录态/受限视频） | 否 |
| `CHANNELS` | 跟踪源 JSON，覆盖 config/channels.json | 否 |

> QQ 邮箱授权码：邮箱设置 → 账户 → 开启 POP3/SMTP 服务 → 生成授权码（16 位）。

**本地 `.env`**：复制 `.env.example` 为 `.env` 填好即可（已被 `.gitignore` 排除，不会入库）。

## 手动触发

- **立即跑一次模式 A**：Actions → 视频跟踪 → Run workflow
- **下载视频到 Releases**：Actions → 视频下载（手动）→ 填 `source_name`（分组名）或 `video_url` → Run workflow

## 注意

- 视频文件一律进 GitHub Releases 而非 git（git 单文件硬限 100MB；Releases 单文件上限 2GB）
- 转录文本/元数据/去重记录为 KB 级，正常入库
- 请仅用于监控/备份你自己拥有版权或已获授权的内容