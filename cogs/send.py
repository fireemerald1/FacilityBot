"""
Send System – private slash command to send messages as the bot.

• /send channel message  → sends a message to the specified channel as the bot.
• Restricted to specific user IDs only.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("facility.send")

# Only these users can use /send
ALLOWED_USER_IDS = {1041613194382286878, 1491212288785514566}


class SendCog(commands.Cog, name="Send"):
    """Private command to send messages as the bot."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="send", description="Send a message to a channel as the bot.")
    @app_commands.describe(
        channel="The channel to send the message to.",
        message="The message content to send.",
    )
    async def send_cmd(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        message: str,
    ):
        if interaction.user.id not in ALLOWED_USER_IDS:
            await interaction.response.send_message(
                "Access denied.", ephemeral=True,
            )
            return

        try:
            await channel.send(message)
            await interaction.response.send_message(
                f"Message delivered to #{channel.name}.", ephemeral=True,
            )
            log.info("User %s sent message to #%s", interaction.user, channel.name)
        except Exception as exc:
            log.warning("Failed to send to #%s: %s", channel.name, exc)
            await interaction.response.send_message(
                f"Failed to deliver message: {exc}", ephemeral=True,
            )


# ── Setup ────────────────────────────────────────────────────────────

async def setup(bot: commands.Bot):
    await bot.add_cog(SendCog(bot))
