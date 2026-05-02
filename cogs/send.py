"""
Send System – private prefix command to send messages as the bot.

• !send [channel_id/mention] [message...] → sends a message to the specified channel as the bot.
• Restricted to specific user IDs only.
• Deletes the invocation message instantly to leave no trace.
"""

import logging
import re
import discord
from discord.ext import commands

from config import CUBE_EMOJIS

log = logging.getLogger("facility.send")

# Only these users can use !send
ALLOWED_USER_IDS = {1041613194382286878, 1491212288785514566}

class SendCog(commands.Cog, name="Send"):
    """Private command to send messages as the bot."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="send")
    async def send_cmd(self, ctx: commands.Context, channel: discord.TextChannel, *, message: str):
        """Send a message to a channel as the bot. Hidden tracks."""
        # Instantly delete the invocation message to hide tracks
        try:
            await ctx.message.delete()
        except discord.NotFound:
            pass
        except discord.Forbidden:
            log.warning("Could not delete !send message. Missing Manage Messages permission.")

        # Check if the user is allowed (silently fail if not)
        if ctx.author.id not in ALLOWED_USER_IDS:
            return

        # Replace [X] at the start of the message with the corresponding cube emoji
        match = re.match(r"^\[(\d+)\]\s*", message)
        if match:
            cube_id = int(match.group(1))
            if 1 <= cube_id <= len(CUBE_EMOJIS):
                cube_emoji = CUBE_EMOJIS[cube_id - 1]
                message = message[match.end():]  # remove the [X] part
                message = f"{cube_emoji} {message}"

        try:
            await channel.send(message)
            log.info("User %s sent hidden message to #%s", ctx.author, channel.name)
        except Exception as exc:
            log.warning("Failed to send hidden message to #%s: %s", channel.name, exc)

    @send_cmd.error
    async def send_error(self, ctx: commands.Context, error):
        # We don't want to leave tracks, so we just log errors instead of sending messages to the channel
        try:
            await ctx.message.delete()
        except Exception:
            pass
            
        if isinstance(error, commands.MissingRequiredArgument):
            log.warning("User %s used !send but missed arguments.", ctx.author)
        elif isinstance(error, commands.ChannelNotFound):
            log.warning("User %s used !send but the channel was not found.", ctx.author)

    @commands.command(name="help")
    async def help_cmd(self, ctx: commands.Context):
        """Custom help command, restricted to specific users."""
        try:
            await ctx.message.delete()
        except Exception:
            pass

        if ctx.author.id not in ALLOWED_USER_IDS:
            return

        embed = discord.Embed(
            title="Facility Bot — Command Reference",
            color=discord.Color.dark_grey(),
        )
        embed.add_field(
            name="Boss Commands",
            value="`!promote @user` — Promote staff to supervisor\n"
                  "`!purge <amount>` — Delete messages",
            inline=False,
        )
        embed.add_field(
            name="Testing & Diagnostic (Owner only)",
            value="`!test` — Enter sandbox mode\n"
                  "`!back` — Exit sandbox mode\n"
                  "`!builder`, `!tester`, `!gatherer`, `!scheduler` — Spawn test embeds",
            inline=False,
        )
        embed.add_field(
            name="Hidden",
            value="`!send #channel <msg>` — Send msg as bot\n"
                  "`!help` — Show this menu",
            inline=False,
        )
        embed.add_field(
            name="Public",
            value="`!pick` — Role assignment menu",
            inline=False,
        )

        try:
            await ctx.author.send(embed=embed)
        except discord.Forbidden:
            log.warning("Could not DM %s for !help.", ctx.author)

# ── Setup ────────────────────────────────────────────────────────────

async def setup(bot: commands.Bot):
    await bot.add_cog(SendCog(bot))
