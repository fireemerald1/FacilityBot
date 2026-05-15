"""
Facility Bot – entry point.

Loads all cogs and registers persistent views so buttons survive restarts.
"""

import os
import asyncio
import logging

import discord
from discord.ext import commands
from dotenv import load_dotenv

from cogs.builder import BuilderView
from cogs.tester import TesterView
from cogs.gatherer import GathererView

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
log = logging.getLogger("facility")

# ── Intents ──────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

# ── Bot instance ─────────────────────────────────────────────────────
bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None,
)

# ── Cog list (add more here later) ──────────────────────────────────
# scheduler loads first so it can manage work-cog lifecycle
EXTENSIONS = [
    "cogs.settings",     # load first — other cogs read from get_setting()
    "cogs.scheduler",
    "cogs.builder",
    "cogs.tester",
    "cogs.gatherer",
    "cogs.roles",
    "cogs.testmode",
    "cogs.send",
    "cogs.admin",
    "cogs.chat",
    "cogs.enforcer",
    "cogs.anomaly",
    "cogs.verification",
]


@bot.event
async def on_ready():
    # Register persistent views so buttons work after a restart.
    # We pass dummy data — the actual state is looked up from custom_id.
    bot.add_view(BuilderView(code="", cog=bot.cogs.get("Builder")))
    bot.add_view(TesterView(slot_key="", original="", mutated="", cog=bot.cogs.get("Tester")))
    bot.add_view(GathererView())

    log.info("Logged in as %s (ID: %s)", bot.user, bot.user.id)
    log.info("Guilds: %s", [g.name for g in bot.guilds])

    # Sync app commands (for future slash commands)
    try:
        synced = await bot.tree.sync()
        log.info("Synced %d app command(s).", len(synced))
    except Exception as exc:
        log.warning("Command sync failed: %s", exc)


@bot.event
async def on_guild_join(guild: discord.Guild):
    """Sync slash commands to a new guild immediately so /c is available right away."""
    log.info("Joined guild: %s (ID: %s) — syncing commands…", guild.name, guild.id)
    try:
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        log.info("Synced %d command(s) to %s.", len(synced), guild.name)
    except Exception as exc:
        log.warning("Failed to sync commands to %s: %s", guild.name, exc)


async def main():
    async with bot:
        for ext in EXTENSIONS:
            await bot.load_extension(ext)
            log.info("Loaded extension: %s", ext)
        await bot.start(os.getenv("BOT_TOKEN"))


if __name__ == "__main__":
    asyncio.run(main())
