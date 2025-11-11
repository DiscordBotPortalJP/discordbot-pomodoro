import asyncio
from datetime import datetime, timedelta
from typing import Iterable, List, Optional, Dict, Tuple, Literal

import discord
from discord.ext import commands
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")

SCHEDULE_MINUTES = (0, 25, 30, 55)

ANNOUNCE = {
    0:  "🍅 作業スタート（25分）",
    25: "☕ 休憩スタート（5分）",
    30: "🍅 作業スタート（25分）",
    55: "☕ 休憩スタート（5分）",
}

JOIN_OVERVIEW = (
    "こんにちは {mention} さん！\n"
    "このボイスチャンネルでは **ポモドーロタイマー** が動いています。\n"
    "- 毎時 **00/25/30/55** に切り替えます（作業25分／休憩5分）\n"
    "- 切り替え時間に通知およびVCステータス更新を行います\n"
)

JOIN_OVERVIEW_COOLDOWN_SEC = 300  # 入室説明の個人クールダウン 5分
VACANCY_STATUS_DELAY_SEC = 5      # 無人化後に status を再設定する遅延
BOT_STAY_IN_VC = True             # 常にVCに参加する対策を有効化

# ----------------- 共通ヘルパ -----------------

def now_jst() -> datetime:
    return datetime.now(JST)

def next_fire_from(t: datetime) -> datetime:
    base = t.replace(second=0, microsecond=0)
    candidates: List[datetime] = []
    for h in (t.hour, (t.hour + 1) % 24):
        for m in SCHEDULE_MINUTES:
            candidates.append(base.replace(hour=h, minute=m))
    candidates = sorted(set(candidates))
    for c in candidates:
        if c > t:
            return c
    return (t + timedelta(minutes=1)).replace(second=0, microsecond=0)

WindowKind = Literal["work", "break"]

def current_window(now: datetime) -> tuple[WindowKind, datetime]:
    m = now.minute
    if 0 <= m < 25:
        end = now.replace(minute=25, second=0, microsecond=0)
        return "work", end
    if 25 <= m < 30:
        end = now.replace(minute=30, second=0, microsecond=0)
        return "break", end
    if 30 <= m < 55:
        end = now.replace(minute=55, second=0, microsecond=0)
        return "work", end
    end = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    return "break", end

def make_status_text_from_now(now: datetime) -> str:
    kind, end = current_window(now)
    hhmm = end.strftime("%H:%M")
    return f"🍅 作業中 ～{hhmm}" if kind == "work" else f"☕ 休憩中 ～{hhmm}"

def make_status_text(minute: int, base: datetime) -> str:
    if minute in (0, 30):  # 作業 25分
        end = (base + timedelta(minutes=25)).strftime("%H:%M")
        return f"🍅 作業中 ～{end}"
    else:  # 休憩 5分
        end = (base + timedelta(minutes=5)).strftime("%H:%M")
        return f"☕ 休憩中 ～{end}"

def chunk_mentions(members: Iterable[discord.Member], head: str, max_len: int = 1900) -> List[str]:
    chunks: List[str] = []
    current = head
    for m in members:
        piece = (" " if current else "") + m.mention
        if len(current) + len(piece) > max_len:
            if current:
                chunks.append(current)
            current = head + " " + m.mention
        else:
            current += piece
    if current:
        chunks.append(current)
    return chunks

# ----------------- 対象VCの選定（Manage Channels 必須） -----------------

def first_manageable_vc(guild: discord.Guild) -> Optional[discord.VoiceChannel]:
    vcs: List[discord.VoiceChannel] = list(guild.voice_channels)
    if not vcs:
        return None
    vcs.sort(key=lambda c: (c.position, c.id))
    me = guild.me
    if me is None:
        return None
    for vc in vcs:
        perms = vc.permissions_for(me)
        if perms.manage_channels:
            return vc
    return None

def vc_humans(vc: discord.VoiceChannel) -> List[discord.Member]:
    return [m for m in vc.members if not m.bot]

def can_send_in(vc: discord.VoiceChannel) -> bool:
    p = vc.permissions_for(vc.guild.me)
    return p.view_channel and p.send_messages

def can_edit_status(vc: discord.VoiceChannel) -> bool:
    p = vc.permissions_for(vc.guild.me)
    return p.manage_channels and hasattr(vc, "edit")

def can_connect(vc: discord.VoiceChannel) -> bool:
    p = vc.permissions_for(vc.guild.me)
    return p.connect

# ----------------- Cog 本体 -----------------

class PomodoroCog(commands.Cog):
    """各 guild で『Manage Channels がある最初のVC』を対象に、告知とVCステータス更新を行う。
       追加対策: BOTは常時VCに参加／無人化後に数秒おいて status を再設定。
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._task: Optional[asyncio.Task] = None
        self._join_last_sent: Dict[Tuple[int, int], datetime] = {}
        # 無人化後の遅延ステータス設定タスク（guild_id -> task）
        self._vacancy_tasks: Dict[int, asyncio.Task] = {}

    # --------- 起動・初期反映 ---------

    @commands.Cog.listener()
    async def on_ready(self):
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._runner(), name="pomodoro-runner")
            print("Pomodoro scheduler started.")
        # 現在窓でステータス即時設定
        asyncio.create_task(self._set_initial_statuses())
        # BOT を対象VCに常駐（許可があれば）
        if BOT_STAY_IN_VC:
            asyncio.create_task(self._ensure_bot_stays_in_all_vcs())

    async def _set_initial_statuses(self):
        now = now_jst()
        status_text = make_status_text_from_now(now)
        for guild in list(self.bot.guilds):
            vc = first_manageable_vc(guild)
            if vc and can_edit_status(vc):
                try:
                    await vc.edit(status=status_text)
                except Exception:
                    pass

    # --------- 常駐ロジック ---------

    async def _ensure_bot_stays_in_all_vcs(self):
        """全guildで対象VCに接続・追従・再接続を試みる。（権限が無ければ黙って諦める）"""
        while not self.bot.is_closed():
            tasks = [self._ensure_bot_in_vc(g) for g in list(self.bot.guilds)]
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.sleep(10)  # 10秒おきに健全性確認

    async def _ensure_bot_in_vc(self, guild: discord.Guild):
        vc = first_manageable_vc(guild)
        if not vc:
            return

        # すでに接続済み？
        vc_client: Optional[discord.VoiceClient] = discord.utils.get(self.bot.voice_clients, guild=guild)
        if vc_client and vc_client.is_connected():
            # 別チャンネルにいたら移動
            if getattr(vc_client, "channel", None) and vc_client.channel.id != vc.id:
                try:
                    await vc_client.move_to(vc)
                except Exception:
                    pass
            return

        # 未接続なら Connect
        if can_connect(vc):
            try:
                await vc.connect(self_deaf=True, timeout=5.0)
            except Exception:
                # 失敗しても黙ってリトライループに任せる
                pass

    # --------- イベント: 入退室 ---------

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member,
                                    before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return
        guild = member.guild
        target_vc = first_manageable_vc(guild)
        if target_vc is None:
            return

        # 入室 → 概要メッセージ（個人宛）
        if after.channel and after.channel.id == target_vc.id and (not before.channel or before.channel.id != target_vc.id):
            if not can_send_in(target_vc):
                return
            key = (guild.id, member.id)
            last = self._join_last_sent.get(key)
            now = now_jst()
            if not last or (now - last).total_seconds() >= JOIN_OVERVIEW_COOLDOWN_SEC:
                self._join_last_sent[key] = now
                try:
                    await target_vc.send(JOIN_OVERVIEW.format(mention=member.mention))
                except Exception:
                    pass

            # 誰か入ったので、無人化遅延タスクが走っていたらキャンセル
            t = self._vacancy_tasks.pop(guild.id, None)
            if t:
                t.cancel()

        # 退室 → 無人化を検知したら遅延して status 再設定
        if before.channel and before.channel.id == target_vc.id and (not after.channel or after.channel.id != target_vc.id):
            # すでに遅延タスクがあるなら作らない
            if guild.id in self._vacancy_tasks:
                return
            # 遅延タスク開始
            self._vacancy_tasks[guild.id] = asyncio.create_task(self._vacancy_status_reset(guild))

    async def _vacancy_status_reset(self, guild: discord.Guild):
        try:
            await asyncio.sleep(VACANCY_STATUS_DELAY_SEC)
            vc = first_manageable_vc(guild)
            if not vc:
                return
            # まだ「人間が0」なら status を現在窓で再設定
            if not vc_humans(vc) and can_edit_status(vc):
                try:
                    await vc.edit(status=make_status_text_from_now(now_jst()))
                except Exception:
                    pass
        finally:
            # タスク登録を掃除
            self._vacancy_tasks.pop(guild.id, None)

    # --------- 時報スケジューラ ---------

    async def _runner(self):
        while not self.bot.is_closed():
            target = next_fire_from(now_jst())
            await asyncio.sleep(max(0.0, (target - now_jst()).total_seconds()))
            try:
                await self._fire_once(target)
            except Exception as e:
                print("[Pomodoro] fire error:", e)

    async def _fire_once(self, target_jst: datetime):
        minute = target_jst.minute
        body_text = ANNOUNCE[minute]
        status_text = make_status_text(minute, target_jst)
        for guild in list(self.bot.guilds):
            try:
                await self._process_guild(guild, body_text, status_text)
            except Exception as e:
                print(f"[Pomodoro] guild {guild.id} error:", e)

    async def _process_guild(self, guild: discord.Guild, body_text: str, status_text: str):
        vc = first_manageable_vc(guild)
        if vc is None:
            return

        # ステータス更新（在室0でも）
        if can_edit_status(vc):
            try:
                await vc.edit(status=status_text)
            except Exception:
                pass

        # 在室者がいる場合のみメンション告知
        humans = vc_humans(vc)
        if not humans or not can_send_in(vc):
            return
        for chunk in chunk_mentions(humans, head=body_text):
            await vc.send(chunk)

async def setup(bot: commands.Bot):
    await bot.add_cog(PomodoroCog(bot))
