"""
Settings System – runtime configuration management.

• !set <variable> <value>  → change a setting (Boss only).
• !settings                → view all current settings.
• !reset                   → restore all settings to defaults.

Settings are persisted to data/settings.json and loaded on boot.
All other cogs read from get_setting() instead of hardcoded values.
"""

import json
import os
import logging

from discord.ext import commands
import discord

from config import SETTINGS_FILE, DEFAULT_SETTINGS
from utils.permissions import is_boss

log = logging.getLogger("facility.settings")

# ── In-memory settings cache ────────────────────────────────────────

_settings: dict = {}


def _load() -> dict:
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save() -> None:
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(_settings, f, indent=2, ensure_ascii=False)


def _init_settings() -> None:
    """Load persisted overrides on top of defaults."""
    global _settings
    _settings = DEFAULT_SETTINGS.copy()
    _settings.update(_load())


def get_setting(key: str):
    """Read a setting value.  All cogs should use this."""
    return _settings.get(key, DEFAULT_SETTINGS.get(key))


def set_setting(key: str, value) -> None:
    """Write a setting value and persist."""
    _settings[key] = value
    _save()


def reset_settings() -> None:
    """Restore every setting to its default."""
    global _settings
    _settings = DEFAULT_SETTINGS.copy()
    if os.path.exists(SETTINGS_FILE):
        os.remove(SETTINGS_FILE)


# Initialise on import so values are available immediately
_init_settings()


# ── Cog ──────────────────────────────────────────────────────────────

class SettingsCog(commands.Cog, name="Settings"):
    """Boss-only runtime configuration."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="set")
    async def set_cmd(self, ctx: commands.Context, variable: str, value: str):
        """Change a facility setting.  Boss only."""
        if not is_boss(ctx.author):
            await ctx.send("Access denied. Boss clearance required.", delete_after=10)
            return

        if variable not in DEFAULT_SETTINGS:
            valid = ", ".join(f"`{k}`" for k in DEFAULT_SETTINGS)
            await ctx.send(
                f"Unknown variable `{variable}`. Valid options: {valid}",
                delete_after=15,
            )
            return

        # All current settings are integers
        try:
            typed_value = int(value)
        except ValueError:
            await ctx.send("Value must be an integer.", delete_after=10)
            return

        if typed_value <= 0:
            await ctx.send("Value must be greater than 0.", delete_after=10)
            return

        set_setting(variable, typed_value)
        await ctx.send(
            f"`{variable}` updated to `{typed_value}`.",
            delete_after=10,
        )
        log.info("Boss %s set %s = %s", ctx.author, variable, typed_value)

    @set_cmd.error
    async def set_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("Usage: `!set <variable> <value>`", delete_after=10)

    @commands.command(name="settings")
    async def settings_cmd(self, ctx: commands.Context):
        """Display all current settings.  Boss only."""
        if not is_boss(ctx.author):
            await ctx.send("Access denied. Boss clearance required.", delete_after=10)
            return

        lines = []
        for key in sorted(DEFAULT_SETTINGS):
            current = get_setting(key)
            default = DEFAULT_SETTINGS[key]
            marker = " ✎" if current != default else ""
            lines.append(f"`{key}` = **{current}**{marker}")

        embed = discord.Embed(
            title="Facility Settings",
            description="\n".join(lines),
            color=discord.Color.dark_grey(),
        )
        embed.set_footer(text="✎ = modified from default.  Use !reset to restore.")
        await ctx.send(embed=embed, delete_after=30)

    @commands.command(name="reset")
    async def reset_cmd(self, ctx: commands.Context):
        """Reset all settings to defaults.  Boss only."""
        if not is_boss(ctx.author):
            await ctx.send("Access denied. Boss clearance required.", delete_after=10)
            return

        reset_settings()
        await ctx.send("All settings restored to defaults.", delete_after=10)
        log.info("Boss %s reset all settings to defaults.", ctx.author)


# ── Setup ────────────────────────────────────────────────────────────

async def setup(bot: commands.Bot):
    await bot.add_cog(SettingsCog(bot))
