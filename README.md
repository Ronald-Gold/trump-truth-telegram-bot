# Trump Truth Social → Telegram Bot

把特朗普总统在 Truth Social 的最新推文实时（每 5 分钟）转发到你的 Telegram，并支持在 Telegram 内发命令查询历史推文。

- 数据源：[trumpstruth.org](https://trumpstruth.org)（非营利机构 Defending Democracy Together 维护的公开 RSS 归档），无需 Truth Social 账号。
- 内容：英文原文 + 中文翻译 + 图片/视频（带 AI 生成的中英文图片描述）+ 原帖直达链接。
- 部署：GitHub Actions 24 小时自动跑，无需开机、无需服务器、无需信用卡。
- **交互式命令**：`/recent N`、`/date YYYY-MM-DD`、`/post <id>`、`/help` —— 直接在 Telegram 给 bot 发即可。

---

## 1. 工作原理（一图看懂）

```
┌──────────────────────┐  每5分钟拉取  ┌──────────────────────┐
│  trumpstruth.org/feed │──────────────▶│  GitHub Actions      │
│  (公开 RSS 归档)      │               │  运行 src/bot.py      │
└──────────────────────┘               └──────────────────────┘
                                                  │
                                  Telegram Bot API│ 推送消息
                                                  ▼
                                       ┌─────────────────────┐
                                       │  @fbuilders_bot      │
                                       └─────────────────────┘
                                                  │
                              ┌───────────────────┼───────────────────┐
                              ▼                                       ▼
                ┌────────────────────────┐              ┌────────────────────────┐
                │ 你的账号 6305691957     │              │ 你的账号 7371196144     │
                └────────────────────────┘              └────────────────────────┘
```

---

## 2. 一次性部署步骤（按顺序做）

### 2.1 在 Telegram 里让 bot "认识" 你的两个账号 ⚠️ 最关键

> Telegram 的硬规则：**机器人只能向主动联系过它的用户发消息**。如果你不给 `@fbuilders_bot` 发过任何消息，机器人没法主动找你。

操作（**两个账号都要做一次**）：

1. 用账号 `6305691957` 登录 Telegram，搜索 `@fbuilders_bot`，打开聊天，**点底部 `START` 或发一条 `/start`**。
2. 切换到账号 `7371196144`，重复上一步。

### 2.2 拿到 @fbuilders_bot 的 Token

1. 在 Telegram 里搜 `@BotFather` 并打开聊天。
2. 发送 `/mybots`，从列表里选 `@fbuilders_bot`。
3. 点 `API Token` → 屏幕上会显示一段类似 `7878787878:AAExxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` 的字符串，**这就是 Token**，复制下来妥善保存。
4. **不要把 Token 发给任何人，也不要写进代码里提交到 GitHub**。

### 2.3 把项目代码上传到 GitHub

#### 选项 A：通过 Cursor / VS Code 图形界面（推荐新手）

1. 在 [github.com](https://github.com) 右上角点 `+` → `New repository`。
2. 仓库名填 `trump-truth-telegram-bot`，可见性建议选 **Private**（私有，免费用户每月 2000 分钟 Actions 配额对这个 bot 来说够用）。
3. **不要勾选** "Initialize with README"。
4. 创建后，按页面提示在本地终端执行（已为你预留示例命令，可直接复制）：

```bash
cd C:\Users\ITadmin1\Projects\trump-truth-telegram-bot
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/<你的GitHub用户名>/trump-truth-telegram-bot.git
git push -u origin main
```

#### 选项 B：用 GitHub CLI（如果已经装了 `gh`）

```bash
cd C:\Users\ITadmin1\Projects\trump-truth-telegram-bot
git add . && git commit -m "Initial commit"
gh repo create trump-truth-telegram-bot --private --source=. --remote=origin --push
```

### 2.4 在 GitHub 仓库里添加 Secrets（保存 Token）

1. 打开仓库主页，点上方 `Settings` 标签。
2. 左边菜单选 `Secrets and variables` → `Actions`。
3. 点 `New repository secret`，**逐条**添加下面 2 个 secret：

| 名字（必须完全一致） | 值 |
|---|---|
| `TELEGRAM_BOT_TOKEN` | 上一步拿到的 token，例如 `7878787878:AAE...` |
| `TELEGRAM_CHAT_IDS` | `6305691957,7371196144` （英文逗号分隔，不要空格） |

> 这些值只在 GitHub Actions 运行时被读取，**不会出现在代码或日志里**。

### 2.5 让 Actions 跑起来

1. 仓库主页 → `Actions` 标签。
2. 第一次进入会让你点 `I understand my workflows, go ahead and enable them`，点同意。
3. 左边列表里会看到 `Poll Trump Truth Social` 工作流，点进去 → 右边 `Run workflow` 按钮 → 点 `Run workflow` 立即跑一次（验证配置）。
4. 30 秒后刷新，应该能看到一条绿色的运行记录。点进去看日志。
5. **去 Telegram 看推送是否到达**。
6. 之后每 5 分钟自动跑，无需任何操作。

---

## 3. 验证 chat_id（可选但推荐）

如果你不确定 `6305691957` / `7371196144` 是不是真的对应你两个账号，可以在 Telegram 里：

- 搜索 `@userinfobot` 并打开聊天。
- 发送任意消息，bot 会回复你的 `Id`。把这个数字与你保存的对照。

---

## 4. 本地手动运行（可选 - 用于排错）

```powershell
cd C:\Users\ITadmin1\Projects\trump-truth-telegram-bot

# 第一次：用清华镜像安装依赖（中国大陆网络 PyPI 可能不稳）
py -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 复制示例环境变量并编辑
Copy-Item .env.example .env
notepad .env
# 把 TELEGRAM_BOT_TOKEN 改成真实 token，保存关闭

# 加载 .env 并运行
$env:TELEGRAM_BOT_TOKEN = (Get-Content .env | Where-Object {$_ -match '^TELEGRAM_BOT_TOKEN='}) -replace '^TELEGRAM_BOT_TOKEN=',''
$env:TELEGRAM_CHAT_IDS = (Get-Content .env | Where-Object {$_ -match '^TELEGRAM_CHAT_IDS='}) -replace '^TELEGRAM_CHAT_IDS=',''
py src/bot.py
```

成功后会在 Telegram 收到最新 1-2 条 Truth Social 推文。

---

## 5. 在 Telegram 里发命令查询历史推文

直接给 `@fbuilders_bot` 发以下命令（建议优先用对它发过 `/start` 的账号）：

| 命令 | 作用 | 示例 |
|---|---|---|
| `/help` | 显示帮助 | `/help` |
| `/recent N` | 推送最近 N 条历史推文（1–20） | `/recent 10` |
| `/date YYYY-MM-DD` | 推送某天的所有推文（最多 25 条） | `/date 2026-05-20` |
| `/post <id>` | 推送特定推文（id 是 trumpstruth.org/statuses/ 后面的数字） | `/post 38716` |

**注意**：
- 命令响应延迟 0–5 分钟（GitHub Actions 5 分钟跑一次时才处理你的命令）。这是免费方案的固有限制。
- 查询结果**只发回给发起命令的账号**（不会打扰另一个账号）。
- 只有 `TELEGRAM_CHAT_IDS` 列表里的账号可以发命令，其他人的命令会被忽略。

如果想立刻补发一批历史推文（不等命令的 5 分钟延迟）：去 GitHub 仓库 `Actions` → `Poll Trump Truth Social` → `Run workflow` → 在 `max_new` 输入框填想发的条数（比如 `20`）→ `Run workflow`。

## 6. 调整与玩法

| 需求 | 怎么改 |
|---|---|
| 改推送频率 | `.github/workflows/poll.yml` 的 cron。注意 GitHub Actions 最快 5 分钟。 |
| 一次最多推几条（防补发洪水） | 仓库 `Settings → Variables → Actions` 添加变量 `MAX_NEW_PER_RUN`，默认 8。 |
| 想加更多接收账号 | 在 secret `TELEGRAM_CHAT_IDS` 里追加 chat_id（用英文逗号分隔）。新账号别忘了先 /start。 |
| 想加进群 / 频道 | 把 bot 拉进群/频道、给管理员权限。群 chat_id 通常是负数，用 `@userinfobot` 在群里查到后填进 secret。 |
| 暂停推送 | 仓库 `Settings → Actions → General → Disable actions`。 |

---

## 7. 故障排查

| 现象 | 排查 |
|---|---|
| Actions 跑成功但 Telegram 没收到 | 99% 是没给 bot `/start`。两个账号都要 /start 一次。然后 `Re-run jobs`。 |
| Actions 红色失败：`401 Unauthorized` | `TELEGRAM_BOT_TOKEN` 写错了，去 Settings → Secrets 改正。 |
| Actions 红色失败：`chat not found` | `TELEGRAM_CHAT_IDS` 不对，或者该账号没 /start。 |
| 翻译都是英文 | 极少数情况下 Google Translate 临时不可用，下一轮会自动重试。 |
| 同一条推文被推送多次 | 不应该发生。如果发生，看仓库根的 `state.json` 是否被 Actions 写回。 |
| 想看完整日志 | Actions 标签 → 选某次运行 → 展开 `Run bot` 步骤。 |

---

## 8. 隐私与合规

- **数据源**：[trumpstruth.org](https://trumpstruth.org/faq) 是 Defending Democracy Together 运营的公开归档，仅含 @realDonaldTrump 的公开发帖。
- **本项目**：仅做 RSS 转发与翻译，不收集你的任何个人数据，不与 Truth Social 直接交互。
- **Token 安全**：Token 通过 GitHub Encrypted Secrets 注入，不会写入仓库或日志。`.env` 已被 `.gitignore` 排除。

---

## 9. 文件结构

```
trump-truth-telegram-bot/
├── .github/workflows/poll.yml    # GitHub Actions 定时任务
├── src/
│   └── bot.py                    # 主程序
├── requirements.txt              # Python 依赖
├── .env.example                  # 本地运行用环境变量示例
├── .gitignore
├── state.json                    # 已推送过的 status ID（自动维护）
└── README.md                     # 本文件
```

---

## 10. License

仅供个人学习与信息消费用途。Trump 的 Truth Social 内容版权归原作者所有；trumpstruth.org 数据使用请遵守其[服务条款](https://trumpstruth.org/faq)。
