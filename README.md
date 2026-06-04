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

| 変数 | 必須 | 説明 |
| --- | --- | --- |
| `DISCORD_BOT_TOKEN` | はい | Discord Bot token |
| `POMODORO_STAY_IN_VC` | いいえ | `true` の場合、対象VCにBotを常駐させます。既定値: `false` |
| `OPS_LOG_HUB_URL` | いいえ | ops-log-hub 送信先 |
| `OPS_LOG_HUB_KEY` | いいえ | ops-log-hub 送信用 key |
| `OPS_LOG_PROJECT` | いいえ | ops-log project 名。既定値: `discordbot-pomodoro` |
| `OPS_LOG_ENVIRONMENT` | いいえ | `production` / `development` など |

## 必要権限・Intents

- View Channel
- Send Messages
- Manage Channels
- Connect (`POMODORO_STAY_IN_VC=true` の場合)
- Voice States Intent

Message Content Intent は不要です。

## 運用ログ

`OPS_LOG_HUB_URL` と `OPS_LOG_HUB_KEY` が設定されている場合のみ、以下のイベントを ops-log-hub に送信します。

- `startup`: Bot 起動完了
- `config_error`: extension 読み込みの失敗
- `command_error`: slash command / prefix command の失敗
- `notification_failed`: ポモドーロ通知・VC処理の失敗

ログには secret 値や不要な個人情報は含めず、guild/channel など調査に必要な最小限の情報だけを入れます。

## ローカル実行

```bash
cp .env.example .env
python -m pip install -r requirements.txt
python main.py
```
