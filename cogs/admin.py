"""
Admin System – boss-only utilities.

• !purge [amount] → deletes the specified number of messages in the current channel.
"""

import logging

import discord
from discord.ext import commands

from utils.permissions import is_boss

log = logging.getLogger("facility.admin")

class AdminCog(commands.Cog, name="Admin"):
    """Handles boss-level administrative commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="purge")
    async def purge_cmd(self, ctx: commands.Context, amount: int):
        """Delete a specified number of messages. Boss only."""
        if not is_boss(ctx.author):
            await ctx.send("Access denied. Boss clearance required.", delete_after=10)
            return

        if amount <= 0:
            await ctx.send("Amount must be greater than 0.", delete_after=10)
            return

        try:
            # We delete `amount + 1` to include the `!purge` command message itself
            deleted = await ctx.channel.purge(limit=amount + 1)
            # Send a temporary confirmation message
            msg = await ctx.send(f"Deleted {len(deleted) - 1} message(s).", delete_after=5)
            log.info("User %s purged %d message(s) in #%s", ctx.author, len(deleted) - 1, ctx.channel.name)
        except discord.Forbidden:
            await ctx.send("I do not have permission to delete messages here.", delete_after=10)
        except discord.HTTPException as exc:
            log.warning("Failed to purge messages: %s", exc)
            await ctx.send(f"An error occurred: {exc}", delete_after=10)

    @purge_cmd.error
    async def purge_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("Usage: `!purge <amount>`", delete_after=10)
        elif isinstance(error, commands.BadArgument):
            await ctx.send("Please provide a valid integer amount.", delete_after=10)

# ── Setup ────────────────────────────────────────────────────────────

async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
