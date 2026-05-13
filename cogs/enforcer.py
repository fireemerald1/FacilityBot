"""
Enforcer System – message enforcement, join/leave handling, and chat logging.

• Deletes normal messages from non-boss users and mutes them for N minutes.
• DMs new members about using /c.
• Removes identities when members leave (rejoin = new identity).
• Logs every /c message to chat-log.json.
"""

import json
import os
import logging
from datetime import datetime, timezone, timedelta

import discord
from discord.ext import commands

import config
from cogs.chat import get_identity, remove_identity
from utils.permissions import is_boss

log = logging.getLogger("facility.enforcer")

WELCOME_DM = (
    "Welcome to the Facility.\n\n"
    "All communication is conducted through the `/c` command.\n"
    "Normal messages are not permitted.\n"
    "Violations will result in temporary muting."
)

VIOLATION_DM = (
    "Protocol violation.\n"
    "Use `/c` to communicate.\n"
    "Mute duration: {minutes} minute(s)."
)


# ── Chat logging ─────────────────────────────────────────────────────

def log_chat_message(
    user_id: int,
    identity_name: str,
    channel_id: int,
    channel_name: str,
    content: str,
) -> None:
    """Append a chat entry to the log file."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "identity": identity_name,
        "channel_id": channel_id,
        "channel_name": channel_name,
        "content": content,
    }

    data = []
    if os.path.exists(config.CHAT_LOG_FILE):
        try:
            with open(config.CHAT_LOG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, ValueError):
            data = []

    data.append(entry)

    with open(config.CHAT_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── Cog ──────────────────────────────────────────────────────────────

class EnforcerCog(commands.Cog, name="Enforcer"):
    """Enforces the /c communication protocol."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Message enforcement ──────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore bots (including webhooks)
        if message.author.bot:
            return

        # Ignore DMs
        if message.guild is None:
            return

        # Ignore prefix commands (! commands)
        if message.content.startswith("!"):
            return

        # Boss is exempt
        if is_boss(message.author):
            return

        # Everything else is a protocol violation
        try:
            await message.delete()
        except (discord.NotFound, discord.Forbidden):
            pass

        # Mute
        mute_minutes = config.MUTE_DURATION
        try:
            until = discord.utils.utcnow() + timedelta(minutes=mute_minutes)
            await message.author.timeout(until, reason="Protocol violation — used normal message instead of /c")
            log.info("Muted %s for %d min (protocol violation).", message.author, mute_minutes)
        except discord.Forbidden:
            log.warning("Cannot mute %s — missing Moderate Members permission.", message.author)

        # DM the user
        try:
            await message.author.send(VIOLATION_DM.format(minutes=mute_minutes))
        except discord.Forbidden:
            log.warning("Cannot DM %s about violation.", message.author)

    # ── Member join ──────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        # Assign identity immediately
        get_identity(member.id)

        # DM welcome message
        try:
            await member.send(WELCOME_DM)
            log.info("Sent welcome DM to %s.", member)
        except discord.Forbidden:
            log.warning("Cannot DM %s on join.", member)

    # ── Member leave ─────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        remove_identity(member.id)
        log.info("Cleared identity for %s (left server).", member)


# ── Setup ────────────────────────────────────────────────────────────

async def setup(bot: commands.Bot):
    await bot.add_cog(EnforcerCog(bot))
