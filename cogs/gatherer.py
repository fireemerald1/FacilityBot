"""
Gatherer System – every 3 hours posts a "has died" embed with a [Gather] button.

• Only users with the Gatherer role can interact.
"""

import random

import discord
from discord.ext import commands, tasks

from config import CHANNEL_GATHERER, GATHERER_INTERVAL_H
from utils.permissions import is_gatherer
from utils.schedule import is_within_active_window


# ── Persistent View ──────────────────────────────────────────────────

class GathererView(discord.ui.View):
    """Single [Gather] button on the gatherer embed."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Gather",
        style=discord.ButtonStyle.primary,
        custom_id="gatherer_gather",
        emoji="🧬",
    )
    async def gather_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not is_gatherer(interaction.user):
            await interaction.response.send_message(
                "❌ You must have the **Gatherer** role to interact.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="🧬 Gathered",
            description=f"Gathered by **{interaction.user.display_name}**",
            color=discord.Color.green(),
        )
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)


# ── Cog ──────────────────────────────────────────────────────────────

class GathererCog(commands.Cog, name="Gatherer"):
    """Manages the Gatherer resource-collection system."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Lifecycle ────────────────────────────────────────────────────

    async def cog_load(self):
        self.gatherer_loop.start()

    async def cog_unload(self):
        self.gatherer_loop.cancel()

    # ── Periodic loop ────────────────────────────────────────────────

    @tasks.loop(hours=GATHERER_INTERVAL_H)
    async def gatherer_loop(self):
        if not is_within_active_window():
            return

        channel = self.bot.get_channel(CHANNEL_GATHERER)
        if channel is None:
            return

        num_a = random.randint(1, 485)
        num_b = random.randint(1, 117)

        embed = discord.Embed(
            title="🧬 Resource Alert",
            description=f"🧬 **{num_a}-{num_b}** has died",
            color=discord.Color.dark_purple(),
        )
        embed.set_footer(text="Gatherers: Click the button below to gather.")

        view = GathererView()
        await channel.send(embed=embed, view=view)

    @gatherer_loop.before_loop
    async def _wait_ready(self):
        await self.bot.wait_until_ready()


# ── Setup ────────────────────────────────────────────────────────────

async def setup(bot: commands.Bot):
    await bot.add_cog(GathererCog(bot))
