# 财经早报自动化系统

每天早上8:30自动生成财经早报并推送到企业微信群。

## 文件说明

- `main.py` — 采集数据 + 调用Claude生成早报
- `send_wechat.py` — 发送消息到企业微信群
- `requirements.txt` — Python依赖包
- `docs/` — GitHub Pages发布目录（存放早报HTML）
- `.github/workflows/daily-brief.yml` — 定时任务配置

## 需要配置的密钥

在GitHub仓库 Settings → Secrets and variables → Actions 中添加：

| 类型 | 名称 | 说明 |
|------|------|------|
| Secret | `ANTHROPIC_API_KEY` | Anthropic API Key（用于调用Claude） |
| Secret | `WECHAT_WEBHOOK_URL` | 企业微信群机器人地址（推荐） |
| Secret | `WXPUSHER_TOKEN` | WxPusher Token（可选，未配置企业微信机器人时使用） |
| Variable | `GITHUB_PAGES_URL` | 你的GitHub Pages地址 |
| Variable | `CLAUDE_MODEL` | Claude模型名（可选，默认 `claude-sonnet-4-20250514`） |
