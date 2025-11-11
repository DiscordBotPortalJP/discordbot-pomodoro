import discord
from discord.ext import commands
from constants import TOKEN

extensions = (
    'pomodoro',
)


class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix='$ ',
            help_command=None,
            intents=discord.Intents.all(),
        )

    async def setup_hook(self):
        for extension in extensions:
            await self.load_extension(f'extensions.{extension}')


def main():
    MyBot().run(TOKEN)


if __name__ == '__main__':
    main()
