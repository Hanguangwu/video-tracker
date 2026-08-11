# AGENTS.md — 视频跟踪系统设计方案

> 本文件是 **设计方案与实施计划**。最终架构、模块划分、实施步骤以本文件为准。
> **状态：设计已确认（用户逐条确认），进入实施阶段。**

---

## 1. 项目目标

用 GitHub Actions 免费额度搭建一套 **视频跟踪/监控管线**：

1. 定时（cron）监控指定 YouTube 源（频道 + 单视频）
2. 检测到新视频 → 提取**转录文本（transcript）** → **Email 推送给用户**
3. 同时通过 **钉钉 / 微信（Server酱）机器人** 推送通知摘要
4. **默认不下载视频文件**（遵循"最好不要存储视频"约束）；仅在手动触发时可选下载
5. 若下载视频：< 100MB 与 ≥100MB 一律走 **GitHub Releases**，绝不塞进 git 历史
6. 架构预留 **Bilibili** 支持（yt-dlp 原生支持，配置层已做平台抽象）

## 2. 当前跟踪源（config/channels.json）

```json
{
  "文昭 Wen Zhao 频道": [
    "https://www.youtube.com/@wenzhaoofficial/videos"
  ],
  "单视频 IKJzTovGaBE": [
    "https://www.youtube.com/watch?v=IKJzTovGaBE"
  ]
}
```

- **格式**：`{"分组名": [URL, ...]}`，与参考文章 channels.json 一致；分组名/URL 都是**非敏感配置**，默认直接提交入库
- **加载优先级**：`CHANNELS` 环境变量（CI 的 GitHub Secret / 本地 `.env`）→ 缺失时读 `config/channels.json`
- **kind 自动推断**：URL 含 `watch?v=`/`bilibili.com/video/` → 单视频（video）；含 `/videos`、`@频道/videos`、`playlist` → 频道/合集扫描（channel）
- `kind: channel` → 每次扫描频道最近 N 个视频，与去重记录对比找出新视频
- `kind: video` → 对固定视频处理一次（拿到转录文本并 Email），之后被去重记录拦住

## 3. 总体架构

```
┌────────────────────── GitHub Actions ──────────────────────┐
│  cron '0 */6 * * *'  +  workflow_dispatch（手动）            │
│         │                                                    │
│  ┌──────▼──────┐   ┌────────────────────────────────┐        │
│  │ track.yml   │──▶│  Python / scripts/track.py      │        │
│  │ (主流程)     │   │  ① 探测新视频(yt-dlp 元数据)      │        │
│  └─────────────┘   │  ② 提取转录(字幕→文本)           │        │
│                    │  ③ Email 发送转录文本            │        │
│                    │  ④ 钉钉/微信通知摘要             │        │
│                    └───────────────┬────────────────┘        │
│                                    │                         │
│                    ┌───────────────▼────────────────┐        │
│                    │  Git 入库(仅文本/元数据，体积小)   │        │
│                    │  archive.txt · seen.txt         │        │
│                    │  data/transcripts/*.txt         │        │
│                    │  data/metadata/*.json           │        │
│                    └───────────────┬────────────────┘        │
│                                    │                         │
│  ┌──────────────┐   ┌──────────────▼─────────────┐           │
│  │ download.yml │──▶│ 手动触发→yt-dlp 下载 mp4      │           │
│  │ (可选/手动)   │   │ → GitHub Releases(不分大小)    │           │
│  └──────────────┘   │ → 通知附下载链接               │           │
│                     └────────────────────────────┘           │
└──────────────────────────────────────────────────────────────┘
```

**存储策略（核心决策）**：
- **入库 git**：去重记录 + 转录文本 + 元数据 JSON（都是 KB 级）
- **GitHub Releases**：视频文件（单文件 <2GB）。Releases 不计入 git 历史、不受 100MB 单文件限制，等效于"存在仓库名下但不污染仓库"
- 视频文件用 `.gitignore` 排除，绝无可能误提交

## 4. 目录结构（目标态）

```
video-tracker/
├── .github/workflows/
│   ├── track.yml                 # 定时监控主流程
│   └── download.yml              # 手动触发：下载视频 → Releases
├── config/
│   └── channels.json             # 默认跟踪源配置（入库；被 CHANNELS env 覆盖）
├── scripts/
│   ├── track.py                  # 主入口编排
│   ├── sources.py                # 加载 CHANNELS env / config/channels.json + 平台抽象
│   ├── transcript.py             # vtt/srt → 纯文本解析，语言优先级选择
│   ├── notify.py                 # 钉钉 webhook / Server酱(微信) 适配器
│   ├── emailer.py                # smtplib 发送转录文本（QQ 邮箱授权码）
│   ├── download.py               # 视频下载（可选模式，--download-archive）
│   └── gh_release.py             # 上传文件到 GitHub Releases
├── archive.txt                   # yt-dlp 视频下载去重（自动维护，入库）
├── data/
│   ├── seen.txt                  # 转录/通知去重（自动维护，入库）
│   ├── transcripts/              # 转录文本 *.txt（入库）
│   ├── metadata/                 # info.json 元数据（入库）
│   └── downloads/                # 视频文件（.gitignore，绝不入库）
├── report.json                   # 最近一次运行报告（入库）
├── requirements.txt              # yt-dlp, requests, PyYAML
├── .env.example                  # 本地配置模板（.env 本身被 .gitignore 排除）
├── .gitignore
├── AGENTS.md                     # 本文件
└── README.md                     # 使用方法 + Secrets 配置说明
```

## 5. 双模式数据流

### 5.1 模式 A：轻量跟踪（默认，track.yml 定时跑）

```
for each group in channels:
  1) 探测：yt-dlp --flat-playlist --playlist-end 20 <url>
            （channel 限最近 20 个；video 直接解析单条）
  2) 过滤：video_id ∉ data/seen.txt  → 新视频列表
  3) 转录：对每个新视频
       yt-dlp --skip-download --write-subs --write-auto-subs
              --sub-langs zh-Hant,zh-Hans,en --sub-format vtt <url>
       → 解析 .vtt 为纯文本 → data/transcripts/<id>.txt
  4) 记录：video_id 追加到 data/seen.txt
  5) Email：每个新视频一封（标题 = 视频标题，正文 = 链接 + 转录全文，
            无字幕视频注明"无可用字幕"）
  6) 通知：钉钉 markdown / Server酱  摘要（本次新视频列表）
  7) 入库：git add data/ archive.txt report.json → commit → push
```

- **字幕语言优先级**：`zh-Hant`（默认首选）→ `zh-Hans` → `en`；若全部无字幕 → 标注"无可用字幕"
- **无新视频** → 跳过 Email 与通知（不打扰），仅更新 report，正常提交
- 转录模式**不下载视频**，因此主流程**无需 ffmpeg**，运行快、省额度（单次 2-4 分钟）

### 5.2 模式 B：视频下载（可选，download.yml 手动触发）

```
workflow_dispatch inputs:
  source_name: 指定 channels.json/CHANNELS 中的分组名（默认全部）
  或 video_url: 直接给单个视频 URL
1) 安装 ffmpeg（合并音视频需要）
2) yt-dlp --download-archive archive.txt   ← 去重核心
          --format bestvideo[height<=1080]+bestaudio/best[height<=1080]
          --merge-output-format mp4
          --output "data/downloads/%(upload_date)s - %(title).100s.%(ext)s"
3) 分流：所有 mp4 统一上传 GitHub Releases
   → softprops/action-gh-release@v2（tag: videos-YYYYMMDD-HHMM）
4) 通知：钉钉/微信 推送 标题+Releases 下载链接
5) archive.txt 入库
```

- **大文件策略**：git 单文件硬限 100MB → 视频一律走 Releases（单文件上限 2GB）。不大于 git 历史。

## 6. 模块职责

| 文件 | 职责 |
|---|---|
| `track.py` | 编排模式 A：探测→转录→Email→通知→入库 |
| `sources.py` | 读 `CHANNELS` env（缺失回退 config/channels.json）；`PLATFORMS` 平台注册表（youtube/bilibili）；URL 规范化 |
| `transcript.py` | 解析 vtt/srt：去 HEADER/序号/时间轴，拼接得纯文本；按 zh-Hant→zh-Hans→en 优先级选字幕 |
| `notify.py` | `DingTalkBot.send(markdown)` / `ServerChanBot.send(title,desp)`；工厂按 env 选择 |
| `emailer.py` | smtplib + email.mime.text（QQ 邮箱 465 SSL 默认）；每新视频一封；`--dry-run` 时打印不发送 |
| `download.py` | 模式 B：调用 yt-dlp 下载，产出文件清单 JSON |
| `gh_release.py` | 用 `GITHUB_TOKEN` 调 Releases API 创建 tag + 上传资产；返回下载链接 |

## 7. GitHub Secrets 清单

| Secret | 用途 | 必需 |
|---|---|---|
| `CHANNELS` | 跟踪源 JSON（覆盖 config/channels.json，内容同文件格式） | 否（有默认文件） |
| `SMTP_HOST` / `SMTP_PORT` | SMTP 服务器（QQ 邮箱：`smtp.qq.com` / `465`） | Email 功能必需 |
| `SMTP_USER` / `SMTP_PASS` | 发信账号 + **QQ 邮箱授权码**（非登录密码） | Email 功能必需 |
| `MAIL_TO` | 收件人邮箱 | Email 功能必需 |
| `MAIL_FROM` | 发件人（默认=SMTP_USER，可省略） | 否 |
| `DINGTALK_WEBHOOK` | 钉钉机器人 webhook | 否 |
| `SERVERCHAN_KEY` | Server酱 SendKey（微信推送） | 否 |
| `COOKIES` | Netscape 格式 Cookie（部分视频需要登录态） | 否 |

> 敏感信息一律只进 env，日志禁止打印。`GITHUB_TOKEN` 由 Actions 自动注入，无需手动配置。
> QQ 邮箱授权码：邮箱设置 → 账户 → 开启 SMTP 服务 → 生成授权码（16 位）。config/channels.json 为非敏感默认配置，直接入库。

## 8. 关键实现细节

### 8.1 去重双注册表（防两套逻辑互相干扰）
- `archive.txt`：yt-dlp 的 `--download-archive` 维护，只记录**真下载过视频**的 ID
- `data/seen.txt`：转录/通知维护，记录**处理过转录**的 ID
- 关键点：模式 A 只写 seen.txt、不污染 archive.txt → 之后手动补下载视频时，yt-dlp 不会跳过

### 8.2 新视频判定
- `--flat-playlist --playlist-end 20` 取频道最近 20 条（轻量、不下载）
- 与 `seen.txt` 求差 → 新视频；对 `kind: video` 直接处理单条
- 判定失败容错：yt-dlp 非零退出 ≠ 失败（如"已在 archive"），需按 stdout/stderr 特征区分

### 8.3 转录方案（不本地跑 Whisper）
- 用 YouTube **自动字幕/CC 字幕**：`--write-auto-subs --write-subs --sub-langs zh-Hant,zh-Hans,en`
- **字幕语言优先级**：`zh-Hant`（默认首选）→ `zh-Hans` → `en`；全部无字幕则标注"无可用字幕"
- `.vtt` → 去时间轴 → 纯文本，KB 级，直接入库 + Email
- 无字幕时降级：标记"无可用字幕"，通知中提示，不阻塞流程
- （未来增强：可选 whisper 本地转录，标记为后续工作，不进首版）

### 8.4 大文件分流
- 视频从不 commit：`data/downloads/` 在 `.gitignore`
- Releases 每文件上限 2GB，100MB 分割不是硬需求（参考文章以 100MB 为 git 红线，这里视频根本不进 git，统一上传 Releases 即可）
- 若未来选云存储（OSS/R2/S3），预留 `gh_release.py` 同接口的 `storage.py`

### 8.5 安全
- `.gitignore`：`data/downloads/`、`cookies*.txt`、`.env`、`*.part`、`__pycache__/`
- Cookie/Token/webhook 只存在 Secrets / `.env` → env
- 脚本统一 `--sleep-interval 2 --max-sleep-interval 5 --retries 3` 降低平台压力与封禁风险

## 9. 定时频率

- 主流程：`cron: '0 */6 * * *'`（每 6 小时，UTC；可后续按需调密）
- GitHub 限制：cron 最短 5 分钟粒度、同一仓库每小时最多约 75 次触发，当前频率远低于限制
- 公开仓库额度无限；私有仓库月 2000 分钟，当前频率约 4×5=20 分钟/天，安全

## 10. Bilibili 扩展预留（后续接入）

- `sources.py` 已有 `platform` 字段与注册表：`bilibili` → `space.bilibili.com/{uid}/video`
- yt-dlp 原生支持 bilibili extractor 与 CC 字幕（`--write-subs`），transcript.py 复用语言映射
- 通知/Email/去重逻辑与平台无关，零改动
- 接入步骤（届时）：① channels.json 加 bilibili 源 ② 验证字幕语言码 ③ 本地试跑

## 11. 实施步骤（待确认后执行）

1. 初始化：`config/channels.json`、`.gitignore`、`requirements.txt`（yt-dlp、requests、PyYAML）
2. 实现脚本：`sources.py` → `transcript.py` → `notify.py` → `emailer.py` → `track.py`
3. 编写 `.github/workflows/track.yml`（cron + dispatch，含 commit 回写）
4. 编写 `.github/workflows/download.yml` + `download.py` + `gh_release.py`（可选模式）
5. 更新 `README.md`（Secret 配置、手动触发说明、本地试跑说明）
6. 本地验证：`python scripts/track.py --dry-run`（不真发邮件/通知）
7. 部署：push → 配置 Secrets → 手动触发一次 track.yml 验收

## 12. 验收标准

- [ ] `track.py` 运行后，新视频生成 `data/transcripts/*.txt`
- [ ] 收到 Email：标题为视频标题、正文含链接与转录全文
- [ ] 收到钉钉/微信通知摘要
- [ ] 二次运行无重复（seen.txt 去重生效，无新视频时不骚扰）
- [ ] 手动触发 `download.yml` → Releases 出现 mp4，通知含下载链接
- [ ] 全程日志无 Cookie/Token 泄露

---

**当前源规模预估**
- 文昭频道频率约每周 2-7 条新视频；转录模式单次运行 2-4 分钟
- 单视频源一次性处理，之后恒被 seen.txt 拦截
- GitHub Actions 消耗：公开仓库无限额度，无忧