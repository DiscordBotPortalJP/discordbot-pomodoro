import discord
from discord.ext import commands
from constants import TOKEN
from utils.ops_log import emit_command_error
from utils.ops_log import emit_exception_event
from utils.ops_log import emit_startup_event

extensions = (
    'pomodoro',
)


class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.voice_states = True

        super().__init__(
            command_prefix='$ ',
            help_command=None,
            intents=intents,
        )
        self._startup_event_sent = False

    async def setup_hook(self):
        try:
            for extension in extensions:
                await self.load_extension(f'extensions.{extension}')
        except Exception as error:
            await emit_exception_event(
                'config_error',
                'Discord Bot setup failed',
                error,
            )
            raise
        self.tree.on_error = self.on_app_command_error

    async def on_ready(self):
        if self._startup_event_sent:
            return
        self._startup_event_sent = True
        await emit_startup_event(self)

    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: discord.app_commands.AppCommandError,
    ):
        await emit_command_error(interaction, error)

        message = 'コマンド実行中にエラーが発生しました。しばらくしてからもう一度お試しください。'
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        await emit_exception_event(
            'command_error',
            f'Prefix command failed: {ctx.command}',
            error,
            actor=str(ctx.author.id) if ctx.author else None,
            safe_details={
                'command': str(ctx.command),
                'guildId': ctx.guild.id if ctx.guild else None,
                'channelId': ctx.channel.id if ctx.channel else None,
            },
        )
        await super().on_command_error(ctx, error)


def main():
    MyBot().run(TOKEN)


if __name__ == '__main__':
    main()
