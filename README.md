# discordbot-pomodoro

ボイスチャンネルでポモドーロの作業時間と休憩時間を案内する単機能 Discord Bot です。

## 機能

- 毎時 `00/25/30/55` 分に作業・休憩の切り替えを通知します。
- 対象ボイスチャンネルのステータスを現在の作業/休憩時間に合わせて更新します。
- ボイスチャンネル参加者がいる場合だけメンション通知します。
- 参加時にポモドーロ運用の概要を案内します。

## 対象ボイスチャンネル

Bot が `Manage Channels` を持つ最初のボイスチャンネルを対象にします。

## 環境変数

| Name | Required | Description |
| --- | --- | --- |
| `DISCORD_BOT_TOKEN` | Yes | Discord Bot token |
| `POMODORO_STAY_IN_VC` | No | `true` の場合、対象VCにBotを常駐させます。Default: `false` |
| `OPS_LOG_HUB_URL` | No | ops-log-hub ingest endpoint |
| `OPS_LOG_HUB_KEY` | No | ops-log-hub ingest key |
| `OPS_LOG_PROJECT` | No | ops-log project name. Default: `discordbot-pomodoro` |
| `OPS_LOG_ENVIRONMENT` | No | `production` / `development` など |

## 必要権限・Intents

- View Channel
- Send Messages
- Manage Channels
- Connect (`POMODORO_STAY_IN_VC=true` の場合)
- Voice States Intent

Message Content Intent は不要です。

## Ops logging

`OPS_LOG_HUB_URL` と `OPS_LOG_HUB_KEY` が設定されている場合のみ、以下のイベントを ops-log-hub に送信します。

- `startup`: Bot 起動完了
- `config_error`: extension load の失敗
- `command_error`: slash command / prefix command の失敗
- `notification_failed`: ポモドーロ通知・VC処理の失敗

ログには secret 値や不要な個人情報は含めず、guild/channel など調査に必要な最小限の情報だけを入れます。

## Local run

```bash
cp .env.example .env
python -m pip install -r requirements.txt
python main.py
```
