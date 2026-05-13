"""
Settings System – runtime configuration management.

• !set <variable> <value>  → change a setting (Boss only).
• !settings                → view all current settings.
• !reset                   → restore all settings to defaults.

Settings are persisted to data/settings.json and loaded on boot.
They are injected directly into the config module.
"""

import json
import os
import logging

from discord.ext import commands
import discord

import config
from utils.permissions import is_boss

log = logging.getLogger("facility.settings")

# ── In-memory settings cache ────────────────────────────────────────

ORIGINAL_DEFAULTS = {}
for k in dir(config):
    if k.isupper() and not k.startswith("_"):
        val = getattr(config, k)
        # Only support primitive types or basic structures
        if isinstance(val, (int, float, str, set, list, dict, tuple)):
            ORIGINAL_DEFAULTS[k] = val

SETTINGS_FILE = config.SETTINGS_FILE

def _load() -> dict:
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def _save(overrides: dict) -> None:
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(overrides, f, indent=2, ensure_ascii=False)

def _init_settings() -> None:
    """Load persisted overrides on top of defaults directly onto config module."""
    overrides = _load()
    for k, v in overrides.items():
        if k in ORIGINAL_DEFAULTS:
            orig_val = ORIGINAL_DEFAULTS[k]
            if isinstance(orig_val, set):
                setattr(config, k, set(v))
            elif isinstance(orig_val, tuple):
                setattr(config, k, tuple(v))
            else:
                setattr(config, k, v)

def set_setting(key: str, value) -> None:
    """Write a setting value, apply to config, and persist."""
    setattr(config, key, value)
    
    # Save current differences to settings.json
    overrides = {}
    for k in ORIGINAL_DEFAULTS:
        current = getattr(config, k)
        orig = ORIGINAL_DEFAULTS[k]
        if current != orig:
            # json sets -> lists
            if isinstance(current, set):
                overrides[k] = list(current)
            elif isinstance(current, tuple):
                overrides[k] = list(current)
            else:
                overrides[k] = current
    _save(overrides)

def reset_settings() -> None:
    """Restore every setting to its default."""
    for k, v in ORIGINAL_DEFAULTS.items():
        setattr(config, k, v)
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
    async def set_cmd(self, ctx: commands.Context, variable: str, *, value: str):
        """Change a facility setting.  Boss only."""
        if not is_boss(ctx.author):
            await ctx.send("Access denied. Boss clearance required.", delete_after=10)
            return

        if variable not in ORIGINAL_DEFAULTS:
            await ctx.send(f"Unknown variable `{variable}`.", delete_after=10)
            return

        orig_val = ORIGINAL_DEFAULTS[variable]
        
        try:
            if isinstance(orig_val, int):
                typed_value = int(value)
            elif isinstance(orig_val, float):
                typed_value = float(value)
            elif isinstance(orig_val, set):
                typed_value = {int(x.strip()) for x in value.split(",")}
            elif isinstance(orig_val, str):
                typed_value = value
            else:
                await ctx.send(f"Cannot edit variable of type {type(orig_val).__name__}.", delete_after=10)
                return
        except ValueError:
            await ctx.send(f"Invalid format for {type(orig_val).__name__}.", delete_after=10)
            return

        set_setting(variable, typed_value)
        await ctx.send(f"`{variable}` updated to `{typed_value}`.", delete_after=10)
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
        for key in sorted(ORIGINAL_DEFAULTS):
            current = getattr(config, key)
            default = ORIGINAL_DEFAULTS[key]
            marker = " ✎" if current != default else ""
            lines.append(f"`{key}` = **{current}**{marker}")

        description = "\n".join(lines)
        if len(description) > 4000:
            description = description[:4000] + "... (truncated)"
            
        embed = discord.Embed(
            title="Facility Settings",
            description=description,
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
