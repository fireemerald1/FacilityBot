"""
Builder System – generates codes, lets Builders accept/reject via buttons.

• Max 2 active embeds at a time.
• A new embed is only sent when an existing one is resolved (accepted/rejected).
• Trap code "&^^^&" is accepted silently but never stored.
"""

import discord
from discord.ext import commands, tasks

from config import (
    CHANNEL_BUILDER,
    TRAP_CODE,
    MAX_ACTIVE_EMBEDS,
    BUILDER_CHECK_INTERVAL_S,
)
from utils.code_gen import generate_code
from utils.permissions import is_builder
from storage import load_chamber, get_next_available_slot, set_slot
from utils.schedule import is_within_active_window


# ── Persistent View ──────────────────────────────────────────────────

class BuilderView(discord.ui.View):
    """Accept / Reject buttons attached to a builder code embed."""

    def __init__(self, code: str, cog: "BuilderCog"):
        super().__init__(timeout=None)
        self.code = code
        self.cog = cog

    @discord.ui.button(
        label="Accept",
        style=discord.ButtonStyle.success,
        custom_id="builder_accept",
    )
    async def accept_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not is_builder(interaction.user):
            await interaction.response.send_message(
                "Access denied. Builder clearance required.",
                ephemeral=True,
            )
            return

        # ── Update embed ────────────────────────────────────────────
        embed = discord.Embed(
            title="Code Accepted",
            description=(
                f"Processed by: {interaction.user.display_name}\n"
                f"Code: `{self.code}`"
            ),
            color=discord.Color.dark_green(),
        )

        # Disable both buttons
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)

        # ── Storage ─────────────────────────────────────────────────
        if self.code != TRAP_CODE:
            data = load_chamber()
            slot = get_next_available_slot(data)
            if slot:
                set_slot(slot, self.code, interaction.user.display_name)

        # Remove from active tracking so a new embed can be sent
        self.cog.remove_active(interaction.message.id)

    @discord.ui.button(
        label="Reject",
        style=discord.ButtonStyle.danger,
        custom_id="builder_reject",
    )
    async def reject_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not is_builder(interaction.user):
            await interaction.response.send_message(
                "Access denied. Builder clearance required.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="Code Rejected",
            description=(
                f"Discarded by: {interaction.user.display_name}\n"
                f"Code: `{self.code}`"
            ),
            color=discord.Color.dark_red(),
        )

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)

        # Remove from active tracking – code is discarded
        self.cog.remove_active(interaction.message.id)


# ── Cog ──────────────────────────────────────────────────────────────

class BuilderCog(commands.Cog, name="Builder"):
    """Manages the Builder code-generation system."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Set of message IDs for currently active (unresolved) embeds
        self._active_ids: set[int] = set()

    # ── Lifecycle ────────────────────────────────────────────────────

    async def cog_load(self):
        self.builder_loop.start()

    async def cog_unload(self):
        self.builder_loop.cancel()

    # ── Active-message bookkeeping ───────────────────────────────────

    @property
    def active_count(self) -> int:
        return len(self._active_ids)

    def track_active(self, message_id: int) -> None:
        self._active_ids.add(message_id)

    def remove_active(self, message_id: int) -> None:
        self._active_ids.discard(message_id)

    # ── Periodic loop ────────────────────────────────────────────────

    @tasks.loop(seconds=BUILDER_CHECK_INTERVAL_S)
    async def builder_loop(self):
        """Top up active embeds so there are always up to MAX_ACTIVE_EMBEDS."""
        if not is_within_active_window():
            return
        if self.active_count >= MAX_ACTIVE_EMBEDS:
            return

        channel = self.bot.get_channel(CHANNEL_BUILDER)
        if channel is None:
            return

        needed = MAX_ACTIVE_EMBEDS - self.active_count
        for _ in range(needed):
            code = generate_code()
            embed = discord.Embed(
                title="<:wrench:1500110842526437386> New Code Generated",
                description=f"```\n{code}\n```",
                color=discord.Color.dark_grey(),
            )
            embed.set_footer(text="Awaiting builder input.")

            view = BuilderView(code=code, cog=self)
            msg = await channel.send(embed=embed, view=view)
            self.track_active(msg.id)

    @builder_loop.before_loop
    async def _wait_ready(self):
        await self.bot.wait_until_ready()


# ── Setup ────────────────────────────────────────────────────────────

async def setup(bot: commands.Bot):
    await bot.add_cog(BuilderCog(bot))
