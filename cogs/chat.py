"""
Chat System – webhook-based communication via /c slash command.

• /c <message>  → sends message through a webhook with the user's facility identity.
• Each user gets a unique #XXXXX# name and hex color, stored in identities.json.
• Boss is exempt — can send normal messages.
"""

import json
import os
import random
import re
import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
from utils.permissions import is_boss

log = logging.getLogger("facility.chat")

# ── Message sanitisation ────────────────────────────────────────────

# Patterns to strip from /c messages
_RE_USER_MENTION = re.compile(r"<@!?\d+>")          # <@123> or <@!123>
_RE_ROLE_MENTION = re.compile(r"<@&\d+>")            # <@&123>
_RE_CHANNEL_MENTION = re.compile(r"<#\d+>")           # <#123>
_RE_CUSTOM_EMOJI = re.compile(r"<a?:\w+:\d+>")        # <:name:id> or <a:name:id>
_RE_URL = re.compile(r"https?://\S+", re.IGNORECASE)  # http:// or https://
# Unicode emoji — covers most emoji ranges
_RE_UNICODE_EMOJI = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002702-\U000027B0"  # dingbats
    "\U000024C2-\U0001F251"  # enclosed chars
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U0001FA00-\U0001FA6F"  # chess symbols
    "\U0001FA70-\U0001FAFF"  # symbols extended-A
    "\U00002600-\U000026FF"  # misc symbols
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U0000200D"             # zero-width joiner
    "\U00000023\U000020E3"   # keycap #
    "\U0000002A\U000020E3"   # keycap *
    "]+",
    flags=re.UNICODE,
)


def sanitize_message(text: str) -> str:
    """Strip pings, custom emoji, links, and unicode emoji from a message."""
    text = _RE_USER_MENTION.sub("", text)
    text = _RE_ROLE_MENTION.sub("", text)
    text = _RE_CHANNEL_MENTION.sub("", text)
    text = _RE_CUSTOM_EMOJI.sub("", text)
    text = _RE_URL.sub("", text)
    text = _RE_UNICODE_EMOJI.sub("", text)
    # Collapse multiple spaces and strip
    text = re.sub(r"  +", " ", text).strip()
    return text

# ── Identity management ─────────────────────────────────────────────

def _load_identities() -> dict:
    if os.path.exists(config.IDENTITIES_FILE):
        with open(config.IDENTITIES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_identities(data: dict) -> None:
    with open(config.IDENTITIES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _generate_unique_id(existing: dict) -> str:
    """Generate a unique 5-digit ID not already in use."""
    used_names = {v["name"] for v in existing.values()}
    while True:
        num = random.randint(0, 99999)
        name = f"#{num:05d}#"
        if name not in used_names:
            return name


def _generate_color() -> str:
    """Generate a random hex color (6 chars, no #)."""
    return f"{random.randint(0, 0xFFFFFF):06X}"


def get_identity(user_id: int) -> dict:
    """Get or create a facility identity for a user."""
    data = _load_identities()
    uid = str(user_id)

    if uid not in data:
        name = _generate_unique_id(data)
        color = _generate_color()
        data[uid] = {"name": name, "color": color}
        _save_identities(data)
        log.info("Assigned identity %s (%s) to user %s", name, color, user_id)

    return data[uid]


def remove_identity(user_id: int) -> None:
    """Remove a user's identity (e.g. on leave)."""
    data = _load_identities()
    uid = str(user_id)
    if uid in data:
        removed = data.pop(uid)
        _save_identities(data)
        log.info("Removed identity %s for user %s", removed["name"], user_id)


def get_identity_by_name(name: str) -> int | None:
    """Look up a user ID by their #XXXXX# name.  Returns None if not found."""
    data = _load_identities()
    for uid, info in data.items():
        if info["name"] == name:
            return int(uid)
    return None


def get_identity_by_id_number(id_number: str) -> int | None:
    """Look up a user ID by the 5-digit number (without # wrappers)."""
    target_name = f"#{id_number}#"
    return get_identity_by_name(target_name)


def get_all_identities() -> dict:
    """Return the full identities dict."""
    return _load_identities()


def rotate_all_identities() -> int:
    """Reassign every user a fresh random #XXXXX# and color. Returns count."""
    data = _load_identities()
    if not data:
        return 0

    new_data = {}
    used_names: set[str] = set()

    for uid in data:
        # Generate a unique new name
        while True:
            num = random.randint(0, 99999)
            name = f"#{num:05d}#"
            if name not in used_names:
                break
        used_names.add(name)
        new_data[uid] = {"name": name, "color": _generate_color()}

    _save_identities(new_data)
    log.info("Rotated %d identities.", len(new_data))
    return len(new_data)


# ── Webhook helpers ──────────────────────────────────────────────────

async def get_or_create_webhook(channel: discord.TextChannel) -> discord.Webhook:
    """Reuse an existing bot-owned webhook or create one."""
    try:
        webhooks = await channel.webhooks()
        for wh in webhooks:
            if wh.user == channel.guild.me:
                return wh
    except discord.Forbidden:
        log.warning("No permission to fetch webhooks in #%s", channel.name)

    return await channel.create_webhook(name="Facility Terminal")


def avatar_url_for(color: str) -> str:
    """Return a URL to a solid-color 128×128 image."""
    return f"https://dummyimage.com/128x128/{color}/{color}.png"


# ── Modal ────────────────────────────────────────────────────────────

class ChatModal(discord.ui.Modal, title="Facility Terminal"):
    """Popup text box for sending a message via webhook."""

    message = discord.ui.TextInput(
        label="Message",
        style=discord.TextStyle.paragraph,
        placeholder="Type your message...",
        required=True,
        max_length=2000,
    )

    def __init__(self, cog: "ChatCog"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        identity = get_identity(interaction.user.id)
        name = identity["name"]
        color = identity["color"]
        content = sanitize_message(self.message.value)

        if not content:
            await interaction.response.send_message(
                "Message rejected — no valid content after filtering.",
                ephemeral=True,
            )
            return

        try:
            webhook = await self.cog._get_webhook(interaction.channel)
            await webhook.send(
                content=content,
                username=name,
                avatar_url=avatar_url_for(color),
            )
            await interaction.response.send_message("✓", ephemeral=True)

            # Log the message (lazy import to avoid circular dep)
            from cogs.enforcer import log_chat_message
            log_chat_message(
                user_id=interaction.user.id,
                identity_name=name,
                channel_id=interaction.channel.id,
                channel_name=interaction.channel.name,
                content=content,
            )
        except discord.HTTPException as exc:
            log.warning("Failed to send webhook message: %s", exc)
            self.cog._webhook_cache.pop(interaction.channel.id, None)
            await interaction.response.send_message(
                "Communication error. Try again.",
                ephemeral=True,
            )

        log.info(
            "Chat: %s (%s) in #%s: %s",
            name, interaction.user, interaction.channel.name, content,
        )


# ── Cog ──────────────────────────────────────────────────────────────

class ChatCog(commands.Cog, name="Chat"):
    """Webhook-based communication system."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Cache webhooks per channel to avoid repeated API calls
        self._webhook_cache: dict[int, discord.Webhook] = {}

    async def _get_webhook(self, channel: discord.TextChannel) -> discord.Webhook:
        if channel.id not in self._webhook_cache:
            self._webhook_cache[channel.id] = await get_or_create_webhook(channel)
        return self._webhook_cache[channel.id]

    @app_commands.command(name="c", description="Send a message through the facility terminal.")
    async def c_command(self, interaction: discord.Interaction):
        """Open the facility terminal to type a message."""
        await interaction.response.send_modal(ChatModal(cog=self))


# ── Setup ────────────────────────────────────────────────────────────

async def setup(bot: commands.Bot):
    await bot.add_cog(ChatCog(bot))
