import asyncio
import json
import logging
import traceback
from datetime import datetime, timezone
from urllib import error
from urllib import request

import discord
from discord.ext import commands

from constants import OPS_LOG_ENVIRONMENT
from constants import OPS_LOG_HUB_KEY
from constants import OPS_LOG_HUB_URL
from constants import OPS_LOG_PROJECT

logger = logging.getLogger(__name__)


def is_ops_log_enabled() -> bool:
    return bool(OPS_LOG_HUB_URL and OPS_LOG_HUB_KEY)


async def emit_ops_event(
    event_type: str,
    severity: str,
    title: str,
    *,
    message: str | None = None,
    actor: str | None = None,
    dedupe_key: str | None = None,
    safe_details: dict | None = None,
) -> bool:
    if not is_ops_log_enabled():
        return False

    payload = {
        'eventType': event_type,
        'severity': severity,
        'project': OPS_LOG_PROJECT,
        'environment': OPS_LOG_ENVIRONMENT,
        'title': title,
        'message': message,
        'actor': actor,
        'dedupeKey': dedupe_key,
        'occurredAt': datetime.now(timezone.utc).isoformat(),
        'aiView': {
            'readableSummary': message or title,
            'safeDetails': safe_details or {},
        },
    }

    compact_payload = {key: value for key, value in payload.items() if value is not None}

    try:
        await asyncio.to_thread(_post_event, compact_payload)
        return True
    except Exception:
        logger.exception('Failed to send event to ops-log-hub')
        return False


async def emit_exception_event(
    event_type: str,
    title: str,
    exc: BaseException,
    *,
    actor: str | None = None,
    safe_details: dict | None = None,
) -> bool:
    error_name = exc.__class__.__name__
    return await emit_ops_event(
        event_type,
        'error',
        title,
        message=f'{error_name}: {exc}',
        actor=actor,
        dedupe_key=f'{OPS_LOG_PROJECT}:{event_type}:{error_name}',
        safe_details={
            **(safe_details or {}),
            'errorType': error_name,
            'traceback': ''.join(traceback.format_exception_only(type(exc), exc)).strip(),
        },
    )


async def emit_startup_event(bot: commands.Bot) -> bool:
    return await emit_ops_event(
        'startup',
        'info',
        'Discord Bot started',
        message=f'{bot.user} is ready.',
        safe_details={
            'guildCount': len(bot.guilds),
            'botUser': str(bot.user),
        },
    )


async def emit_command_error(
    interaction: discord.Interaction,
    exc: BaseException,
) -> bool:
    command_name = interaction.command.name if interaction.command else 'unknown'
    return await emit_exception_event(
        'command_error',
        f'Slash command failed: /{command_name}',
        exc,
        actor=str(interaction.user.id) if interaction.user else None,
        safe_details={
            'command': command_name,
            'guildId': interaction.guild_id,
            'channelId': interaction.channel_id,
        },
    )


def _post_event(payload: dict) -> None:
    if not OPS_LOG_HUB_URL or not OPS_LOG_HUB_KEY:
        return

    data = json.dumps(payload).encode('utf-8')
    req = request.Request(
        OPS_LOG_HUB_URL,
        data=data,
        method='POST',
        headers={
            'content-type': 'application/json',
            'x-log-hub-key': OPS_LOG_HUB_KEY,
        },
    )

    try:
        with request.urlopen(req, timeout=5) as response:
            response.read()
    except error.HTTPError as exc:
        body = exc.read().decode('utf-8', errors='replace')
        raise RuntimeError(f'ops-log-hub returned {exc.code}: {body}') from exc
