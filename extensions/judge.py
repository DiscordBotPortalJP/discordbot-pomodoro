import discord
from discord import app_commands
from discord.ext import commands
from daug.utils.dpyexcept import excepter
from daug.utils.dpylog import dpylogger

CHANNEL_PROFILE_ID = 1422394293066137622
CHANNEL_JUDGE_MEMBER_ID = 1461308298694365294
CHANNEL_JUDGE_STAFF_ID = 1461310292989575296
CHANNEL_IDS = (
    CHANNEL_JUDGE_MEMBER_ID,
    CHANNEL_JUDGE_STAFF_ID,
)
VOTES = (
    'オススメ',
    '良さそう',
    'わからない',
    '苦手',
    '要注意',
)


def initialize_votes_embed() -> discord.Embed:
    embed = discord.Embed(description='投票内訳')
    for vote in VOTES:
        embed.add_field(name=f'{vote}（0票）', value='', inline=False)
    return embed


def upvote(message: discord.Message, member: discord.Member, index: int) -> str:
    value = message.embeds[1].fields[index].value
    if str(member.id) not in value:
        return f'{value} {member.mention}'
    return value


def downvote(message: discord.Message, member: discord.Member, index: int) -> str:
    value = message.embeds[1].fields[index].value
    if str(member.id) in value:
        return ' '.join([user for user in value.split() if str(member.id) not in user])
    return value


def compose_votes_embed(message: discord.Message, member: discord.Member, index: int) -> discord.Embed:
    votes_embed = message.embeds[1]
    for i, vote in enumerate(VOTES):
        value = upvote(message, member, i) if index == i else downvote(message, member, i)
        votes_embed.set_field_at(i, name=f'{vote}（{len(value.split())}票）', value=value, inline=False)
    return votes_embed


async def pick_copied_message(client: discord.Client | commands.Bot, channel_id: int, message_id: int) -> discord.Message | None:
    async for log in client.get_channel(channel_id).history(limit=None):
        if log.author.id != client.user.id:
            continue
        if len(log.embeds) == 0:
            continue
        if log.embeds and log.embeds[0].footer.text == str(message_id):
            return log
    return None


def compose_embed(message: discord.Message) -> discord.Embed:
    color = discord.Colour.default()
    for line in message.content.splitlines():
        if '【性別】' not in line:
            continue
        if '男' in line:
            color = discord.Colour.blue()
        if '女' in line:
            color = discord.Colour.magenta()
    embed = discord.Embed(
        description=message.content,
        timestamp=message.created_at,
        color=color,
    )
    embed.set_author(
        name=str(message.author),
        icon_url=message.author.display_avatar.url,
        url=message.jump_url,
    )
    embed.set_footer(
        text=message.id,
    )
    return embed


async def update_votes(interaction: discord.Interaction, index: int):
    if interaction.channel.id == CHANNEL_JUDGE_MEMBER_ID:
        message = await pick_copied_message(interaction.client, CHANNEL_JUDGE_STAFF_ID, int(interaction.message.embeds[0].footer.text))
    if interaction.channel.id == CHANNEL_JUDGE_STAFF_ID:
        message = interaction.message
    await message.edit(embeds=[message.embeds[0], compose_votes_embed(message, interaction.user, index)])


class VoteButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label=VOTES[0][:-1], emoji='🐰', style=discord.ButtonStyle.green, custom_id='vote:1st')
    @excepter
    @dpylogger
    async def introduce(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        index = 0
        await update_votes(interaction, index)
        await interaction.followup.send(f'「{VOTES[index]}」に投票しました。\n※最新の1票のみ有効です。', ephemeral=True)

    @discord.ui.button(label=VOTES[1][:-1], emoji='🐰', style=discord.ButtonStyle.green, custom_id='vote:2nd')
    @excepter
    @dpylogger
    async def reccomend(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        index = 1
        await update_votes(interaction, index)
        await interaction.followup.send(f'「{VOTES[index]}」に投票しました。\n※最新の1票のみ有効です。', ephemeral=True)

    @discord.ui.button(label=VOTES[2][:-1], emoji='🐰', style=discord.ButtonStyle.blurple, custom_id='vote:3rd')
    @excepter
    @dpylogger
    async def normal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        index = 2
        await update_votes(interaction, index)
        await interaction.followup.send(f'「{VOTES[index]}」に投票しました。\n※最新の1票のみ有効です。', ephemeral=True)

    @discord.ui.button(label=VOTES[3][:-1], emoji='🐰', style=discord.ButtonStyle.red, custom_id='vote:4th')
    @excepter
    @dpylogger
    async def dislike(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        index = 3
        await update_votes(interaction, index)
        await interaction.followup.send(f'「{VOTES[index]}」に投票しました。\n※最新の1票のみ有効です。', ephemeral=True)

    @discord.ui.button(label=VOTES[4][:-1], emoji='🐰', style=discord.ButtonStyle.red, custom_id='vote:5th')
    @excepter
    @dpylogger
    async def danger(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        index = 4
        await update_votes(interaction, index)
        await interaction.followup.send(f'「{VOTES[index]}」に投票しました。\n※最新の1票のみ有効です。\n※要注意に入れた方にはDMする可能性があります。', ephemeral=True)

    @discord.ui.button(label='取消', style=discord.ButtonStyle.grey, custom_id='vote:cancel')
    @excepter
    @dpylogger
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await update_votes(interaction, -1)
        await interaction.followup.send('投票を取り消しました。', ephemeral=True)


class JudgeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.add_view(VoteButton())

    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(limit="プロフィールチャンネルの直近何件を走査するか（例: 200, 1000）")
    @excepter
    @dpylogger
    async def backfill_profiles(self, interaction: discord.Interaction, limit: app_commands.Range[int, 1, 5000] = 200):
        """
        過去のプロフィール投稿のうち「審査チャンネルへ未転載」のものを探して転載する。
        - 走査対象: CHANNEL_PROFILE_ID の履歴（新しい順）
        - 転載済み判定: CHANNEL_JUDGE_STAFF_ID に footer==元投稿ID の転載が存在するか
        """

        # 早めに応答猶予（件数が多いと時間がかかるため）
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("このコマンドはサーバー内で実行してください。", ephemeral=True)
            return

        profile_ch = guild.get_channel(CHANNEL_PROFILE_ID)
        member_judge_ch = guild.get_channel(CHANNEL_JUDGE_MEMBER_ID)
        staff_judge_ch = guild.get_channel(CHANNEL_JUDGE_STAFF_ID)

        if not isinstance(profile_ch, discord.TextChannel) or \
           not isinstance(member_judge_ch, discord.TextChannel) or \
           not isinstance(staff_judge_ch, discord.TextChannel):
            await interaction.followup.send("チャンネル取得に失敗しました（ID設定を確認してください）。", ephemeral=True)
            return

        scanned = 0
        copied = 0
        skipped = 0
        failed = 0

        # プロフィールチャンネルを新しい順に走査
        async for m in profile_ch.history(limit=limit, oldest_first=False):
            scanned += 1

            # 必要に応じてスキップ条件を調整（例：Bot投稿は除外）
            if m.author.bot:
                skipped += 1
                continue

            # 「スタッフ審査に転載済みか？」で判定（source of truth をスタッフ側に寄せる）
            try:
                already = await pick_copied_message(self.bot, CHANNEL_JUDGE_STAFF_ID, str(m.id))
            except Exception:
                already = None

            if already is not None:
                skipped += 1
                continue

            # 未転載 → 現行 on_message と同じ形式で転載
            try:
                profile_embed = compose_embed(m)

                await member_judge_ch.send(
                    embeds=[profile_embed],
                    view=VoteButton(),
                )

                await staff_judge_ch.send(
                    embeds=[profile_embed, initialize_votes_embed()],
                    view=VoteButton(),
                )

                copied += 1

            except Exception:
                failed += 1

        await interaction.followup.send(
            "バックフィル完了\n"
            f"- 走査: {scanned}\n"
            f"- 転載: {copied}\n"
            f"- スキップ(転載済み/対象外): {skipped}\n"
            f"- 失敗: {failed}",
            ephemeral=True,
        )

    @commands.Cog.listener()
    @excepter
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if message.channel.id != CHANNEL_PROFILE_ID:
            return
        await self.bot.get_channel(CHANNEL_JUDGE_MEMBER_ID).send(embeds=[compose_embed(message)], view=VoteButton())
        await self.bot.get_channel(CHANNEL_JUDGE_STAFF_ID).send(embeds=[compose_embed(message), initialize_votes_embed()], view=VoteButton())

    @commands.Cog.listener()
    @excepter
    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent):
        if payload.channel_id != CHANNEL_PROFILE_ID:
            return
        edited_message = await self.bot.get_channel(payload.channel_id).fetch_message(payload.message_id)
        if edited_message.author.bot:
            return
        for channel_id in CHANNEL_IDS:
            copied_message = await pick_copied_message(self.bot, channel_id, payload.message_id)
            if channel_id == CHANNEL_JUDGE_MEMBER_ID:
                await copied_message.edit(embeds=[compose_embed(edited_message)])
            if channel_id == CHANNEL_JUDGE_STAFF_ID:
                await copied_message.edit(embeds=[compose_embed(edited_message), copied_message.embeds[1]])

    @commands.Cog.listener()
    @excepter
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        if payload.channel_id != CHANNEL_PROFILE_ID:
            return
        for channel_id in CHANNEL_IDS:
            copied_message = await pick_copied_message(self.bot, channel_id, payload.message_id)
            if copied_message is not None:
                try:
                    await copied_message.delete()
                except discord.errors.NotFound:
                    pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(JudgeCog(bot))
