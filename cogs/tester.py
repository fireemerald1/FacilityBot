"""
Tester System – shows test-chamber codes to Testers for verification.

• Max 2 active embeds at a time.
• A new embed is only sent when an existing one is resolved.
• Displays original code + a possibly-mutated copy (10 % mutation chance).
• Buttons are placeholders for future interaction — currently acknowledge only.
"""

import random

import discord
from discord.ext import commands, tasks

from config import (
    CHANNEL_TESTER,
    MAX_ACTIVE_EMBEDS,
    TESTER_CHECK_INTERVAL_S,
)
from utils.code_gen import mutate_code
from utils.permissions import is_tester
from storage import load_chamber, get_filled_slots
from utils.schedule import is_within_active_window


# ── Persistent View ──────────────────────────────────────────────────

class TesterView(discord.ui.View):
    """Verify / Flag buttons for a tester embed."""

    def __init__(self, slot_key: str, original: str, mutated: str, cog: "TesterCog"):
        super().__init__(timeout=None)
        self.slot_key = slot_key
        self.original = original
        self.mutated = mutated
        self.cog = cog

    @discord.ui.button(
        label="Verify",
        style=discord.ButtonStyle.success,
        custom_id="tester_verify",
    )
    async def verify_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not is_tester(interaction.user):
            await interaction.response.send_message(
                "Access denied. Tester clearance required.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="Code Verified",
            description=(
                f"Verified by: {interaction.user.display_name}\n"
                f"Slot: `{self.slot_key}`"
            ),
            color=discord.Color.dark_green(),
        )
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)
        self.cog.remove_active(interaction.message.id)

    @discord.ui.button(
        label="Flag",
        style=discord.ButtonStyle.danger,
        custom_id="tester_flag",
    )
    async def flag_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not is_tester(interaction.user):
            await interaction.response.send_message(
                "Access denied. Tester clearance required.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="Code Flagged",
            description=(
                f"Flagged by: {interaction.user.display_name}\n"
                f"Slot: `{self.slot_key}`"
            ),
            color=discord.Color.dark_red(),
        )
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)
        self.cog.remove_active(interaction.message.id)


# ── Cog ──────────────────────────────────────────────────────────────

class TesterCog(commands.Cog, name="Tester"):
    """Manages the Tester code-verification system."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._active_ids: set[int] = set()

    # ── Lifecycle ────────────────────────────────────────────────────

    async def cog_load(self):
        self.tester_loop.start()

    async def cog_unload(self):
        self.tester_loop.cancel()

    # ── Active-message bookkeeping ───────────────────────────────────

    @property
    def active_count(self) -> int:
        return len(self._active_ids)

    def track_active(self, message_id: int) -> None:
        self._active_ids.add(message_id)

    def remove_active(self, message_id: int) -> None:
        self._active_ids.discard(message_id)

    # ── Periodic loop ────────────────────────────────────────────────

    @tasks.loop(seconds=TESTER_CHECK_INTERVAL_S)
    async def tester_loop(self):
        """Top up active embeds using filled test-chamber slots."""
        if not is_within_active_window():
            return
        if self.active_count >= MAX_ACTIVE_EMBEDS:
            return

        data = load_chamber()
        filled = get_filled_slots(data)
        if not filled:
            return  # nothing to test yet

        channel = self.bot.get_channel(CHANNEL_TESTER)
        if channel is None:
            return

        needed = MAX_ACTIVE_EMBEDS - self.active_count
        for _ in range(needed):
            if not filled:
                break

            slot_key, slot_data = random.choice(filled)
            original = slot_data["code"]
            mutated = mutate_code(original)

            embed = discord.Embed(
                title="<a:TestBall:1500108363395104769> Test Chamber Code",
                description=(
                    f"```\n{original}\n```\n"
                    f"```\n{mutated}\n```"
                ),
                color=discord.Color.dark_grey(),
            )
            embed.set_footer(text=f"Slot: {slot_key} — Awaiting tester input.")

            view = TesterView(
                slot_key=slot_key,
                original=original,
                mutated=mutated,
                cog=self,
            )
            msg = await channel.send(embed=embed, view=view)
            self.track_active(msg.id)

    @tester_loop.before_loop
    async def _wait_ready(self):
        await self.bot.wait_until_ready()


# ── Setup ────────────────────────────────────────────────────────────

async def setup(bot: commands.Bot):
    await bot.add_cog(TesterCog(bot))
