import os
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

# --- 可変パラメータ ---
JOIN_OVERVIEW_COOLDOWN_SEC = 300
VACANCY_STATUS_DELAY_SEC   = 3
BOT_STAY_IN_VC = os.getenv("POMODORO_STAY_IN_VC", "false").lower() in ("1","true","yes")

# -------- 共通ヘルパ --------
def now_jst() -> datetime: return datetime.now(JST)

def next_fire_from(t: datetime) -> datetime:
    base = t.replace(second=0, microsecond=0)
    cand: List[datetime] = []
    for h in (t.hour, (t.hour + 1) % 24):
        for m in SCHEDULE_MINUTES:
            cand.append(base.replace(hour=h, minute=m))
    cand = sorted(set(cand))
    for c in cand:
        if c > t: return c
    return (t + timedelta(minutes=1)).replace(second=0, microsecond=0)

WindowKind = Literal["work", "break"]

def current_window(now: datetime) -> tuple[WindowKind, datetime]:
    m = now.minute
    if 0 <= m < 25:  return "work",  now.replace(minute=25, second=0, microsecond=0)
    if 25 <= m < 30: return "break", now.replace(minute=30, second=0, microsecond=0)
    if 30 <= m < 55: return "work",  now.replace(minute=55, second=0, microsecond=0)
    return "break", (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)

def make_status_text_from_now(now: datetime) -> str:
    kind, end = current_window(now)
    return f"🍅 作業中 ～{end.strftime('%H:%M')}" if kind == "work" else f"☕ 休憩中 ～{end.strftime('%H:%M')}"

def make_status_text(minute: int, base: datetime) -> str:
    if minute in (0, 30): end = (base + timedelta(minutes=25)).strftime("%H:%M"); return f"🍅 作業中 ～{end}"
    else:                 end = (base + timedelta(minutes=5)).strftime("%H:%M");  return f"☕ 休憩中 ～{end}"

def chunk_mentions(members: Iterable[discord.Member], head: str, max_len: int = 1900) -> List[str]:
    chunks: List[str] = []; cur = head
    for m in members:
        piece = (" " if cur else "") + m.mention
        if len(cur) + len(piece) > max_len:
            if cur: chunks.append(cur)
            cur = head + " " + m.mention
        else: cur += piece
    if cur: chunks.append(cur)
    return chunks

# 対象VC選定：Manage Channels を持つ最初のVC
def first_manageable_vc(guild: discord.Guild) -> Optional[discord.VoiceChannel]:
    vcs: List[discord.VoiceChannel] = list(guild.voice_channels)
    if not vcs: return None
    vcs.sort(key=lambda c: (c.position, c.id))
    me = guild.me
    if not me: return None
    for vc in vcs:
        perms = vc.permissions_for(me)
        if perms.manage_channels:  # 管理権限があるVCのみ対象
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
    return vc.permissions_for(vc.guild.me).connect

# -------- Cog 本体 --------
class PomodoroCog(commands.Cog):
    """Manage Channels を持つ“最初のVC”で、在室の有無に関わらず VC ステータスを維持し、
       時報時は在室者へメンション通知（topicは触らない）。"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._task: Optional[asyncio.Task] = None
        self._join_last_sent: Dict[Tuple[int, int], datetime] = {}
        self._vacancy_tasks: Dict[int, asyncio.Task] = {}
        # 新規ギルド用：権限整うまで再試行するタスク
        self._post_join_tasks: Dict[int, asyncio.Task] = {}

    # ----- 汎用：ギルド単位で現在窓のステータスを設定 -----
    async def _set_status_current_for_guild(self, guild: discord.Guild):
        vc = first_manageable_vc(guild)
        if vc and can_edit_status(vc):
            try:
                await vc.edit(status=make_status_text_from_now(now_jst()))
            except Exception:
                pass

    # ----- 起動時 -----
    @commands.Cog.listener()
    async def on_ready(self):
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._runner(), name="pomodoro-runner")
            print("Pomodoro scheduler started.")
        # (1) 起動時：全ギルドの対象VCに現在窓で status を即時設定
        asyncio.create_task(self._set_initial_statuses())
        # 常駐（任意）
        if BOT_STAY_IN_VC:
            asyncio.create_task(self._ensure_bot_stays_in_all_vcs())
        else:
            asyncio.create_task(self._disconnect_from_all_vcs())

    async def _set_initial_statuses(self):
        for guild in list(self.bot.guilds):
            await self._set_status_current_for_guild(guild)

    # ----- 新規ギルド参加時（権限付与完了までリトライ） -----
    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        # (3) 新しいサーバー：Manage Channels が付与されるまで一定時間リトライして設定
        t = asyncio.create_task(self._retry_set_status_until_permitted(guild), name=f"post-join-{guild.id}")
        self._post_join_tasks[guild.id] = t

    @commands.Cog.listener()
    async def on_guild_available(self, guild: discord.Guild):
        # 可用になったタイミングでも同様に試す（再接続など）
        if guild.id not in self._post_join_tasks:
            t = asyncio.create_task(self._retry_set_status_until_permitted(guild), name=f"avail-{guild.id}")
            self._post_join_tasks[guild.id] = t

    async def _retry_set_status_until_permitted(self, guild: discord.Guild, timeout_sec: int = 300):
        start = now_jst()
        try:
            while (now_jst() - start).total_seconds() < timeout_sec and not self.bot.is_closed():
                vc = first_manageable_vc(guild)
                if vc and can_edit_status(vc):
                    await self._set_status_current_for_guild(guild)
                    return
                await asyncio.sleep(5)  # 5秒おきに確認
        finally:
            self._post_join_tasks.pop(guild.id, None)

    # ----- VC常駐（任意機能、関数は残す） -----
    async def _ensure_bot_stays_in_all_vcs(self):
        while not self.bot.is_closed():
            await asyncio.gather(*(self._ensure_bot_in_vc(g) for g in list(self.bot.guilds)), return_exceptions=True)
            await asyncio.sleep(10)

    async def _disconnect_from_all_vcs(self):
        for vc_client in list(self.bot.voice_clients):
            try:    await vc_client.disconnect(force=True)
            except: pass

    async def _ensure_bot_in_vc(self, guild: discord.Guild):
        vc = first_manageable_vc(guild)
        if not vc: return
        vc_client: Optional[discord.VoiceClient] = discord.utils.get(self.bot.voice_clients, guild=guild)
        if vc_client and vc_client.is_connected():
            if getattr(vc_client, "channel", None) and vc_client.channel.id != vc.id:
                try:    await vc_client.move_to(vc)
                except: pass
            return
        if can_connect(vc):
            try:    await vc.connect(self_deaf=True, timeout=5.0)
            except: pass

    # ----- 入退室イベント -----
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member,
                                    before: discord.VoiceState, after: discord.VoiceState):
        if member.bot: return
        guild = member.guild
        target_vc = first_manageable_vc(guild)
        if target_vc is None: return

        # 入室：個人向け概要（クールダウン付）& 無人化遅延タスクがあればキャンセル
        if after.channel and after.channel.id == target_vc.id and (not before.channel or before.channel.id != target_vc.id):
            if can_send_in(target_vc):
                key = (guild.id, member.id)
                last = self._join_last_sent.get(key)
                now = now_jst()
                if not last or (now - last).total_seconds() >= JOIN_OVERVIEW_COOLDOWN_SEC:
                    self._join_last_sent[key] = now
                    try:    await target_vc.send(JOIN_OVERVIEW.format(mention=member.mention))
                    except: pass
            t = self._vacancy_tasks.pop(guild.id, None)
            if t: t.cancel()

        # 退室：在室0になったら数秒後に status を再設定（(2) を満たす）
        if before.channel and before.channel.id == target_vc.id and (not after.channel or after.channel.id != target_vc.id):
            if guild.id in self._vacancy_tasks:
                return
            self._vacancy_tasks[guild.id] = asyncio.create_task(self._vacancy_status_reset(guild))

    async def _vacancy_status_reset(self, guild: discord.Guild):
        try:
            await asyncio.sleep(VACANCY_STATUS_DELAY_SEC)
            vc = first_manageable_vc(guild)
            if not vc: return
            if not vc_humans(vc) and can_edit_status(vc):
                try:    await vc.edit(status=make_status_text_from_now(now_jst()))
                except: pass
        finally:
            self._vacancy_tasks.pop(guild.id, None)

    # ----- 時報スケジューラ（00/25/30/55） -----
    async def _runner(self):
        while not self.bot.is_closed():
            target = next_fire_from(now_jst())
            await asyncio.sleep(max(0.0, (target - now_jst()).total_seconds()))
            try:    await self._fire_once(target)
            except Exception as e:
                print("[Pomodoro] fire error:", e)

    async def _fire_once(self, target_jst: datetime):
        minute = target_jst.minute
        body_text  = ANNOUNCE[minute]
        status_txt = make_status_text(minute, target_jst)
        for guild in list(self.bot.guilds):
            try:    await self._process_guild(guild, body_text, status_txt)
            except Exception as e:
                print(f"[Pomodoro] guild {guild.id} error:", e)

    async def _process_guild(self, guild: discord.Guild, body_text: str, status_text: str):
        vc = first_manageable_vc(guild)
        if vc is None: return

        # 在室0でもステータス更新
        if can_edit_status(vc):
            try:    await vc.edit(status=status_text)
            except: pass

        # 在室者がいるときのみメンション告知
        humans = vc_humans(vc)
        if not humans or not can_send_in(vc): return
        for chunk in chunk_mentions(humans, head=body_text):
            await vc.send(chunk)

async def setup(bot: commands.Bot):
    await bot.add_cog(PomodoroCog(bot))
