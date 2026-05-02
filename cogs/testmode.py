"""
Test Mode – manual embed testing without persistence.

• !test   → enter test mode (sandbox, nothing saved to disk)
• !back   → exit test mode, clean up all test messages
• !builder   → spawn a builder code embed
• !tester    → spawn a tester verification embed
• !gatherer  → spawn a gatherer resource embed
• !scheduler → fire a schedule start/shutdown alert

All test embeds auto-delete after 10 minutes.
Only the Owner role can use these commands.
"""

import asyncio
import logging
import random

import discord
from discord.ext import commands

from config import (
    CHANNEL_ALERT,
    CHANNEL_BUILDER,
    CHANNEL_TESTER,
    CHANNEL_GATHERER,
    TRAP_CODE,
    OUTAGE_MESSAGES,
)
from utils.code_gen import generate_code, mutate_code
from utils.permissions import is_owner
from storage import load_chamber, get_filled_slots, get_next_available_slot, set_slot
from teststate import (
    is_test_mode,
    enable_test_mode,
    disable_test_mode,
    get_test_messages,
    track_test_message,
)

log = logging.getLogger("facility.testmode")

AUTO_DELETE_SECONDS = 600  # 10 minutes


# ── Helpers ──────────────────────────────────────────────────────────

async def auto_delete(msg: discord.Message, delay: int = AUTO_DELETE_SECONDS):
    """Delete *msg* after *delay* seconds (fire-and-forget)."""
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except (discord.NotFound, discord.Forbidden):
        pass


def schedule_test_delete(msg: discord.Message) -> None:
    """Track a test message and schedule its auto-deletion."""
    track_test_message(msg)
    asyncio.create_task(auto_delete(msg))


# ── Test-mode Views (mirrors of the real ones, but non-persistent) ───

class TestBuilderView(discord.ui.View):
    """Accept / Reject buttons for a test builder embed."""

    def __init__(self, code: str):
        super().__init__(timeout=AUTO_DELETE_SECONDS)
        self.code = code

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_owner(interaction.user):
            await interaction.response.send_message("❌ Test mode: Owner only.", ephemeral=True)
            return

        embed = discord.Embed(
            title="Code Accepted",
            description=(
                f"**Accepted by:** {interaction.user.display_name}\n"
                f"**Full code:** `{self.code}`"
            ),
            color=discord.Color.green(),
        )
        # Store in test chamber (memory only)
        if self.code != TRAP_CODE:
            data = load_chamber()
            slot = get_next_available_slot(data)
            if slot:
                set_slot(slot, self.code, interaction.user.display_name)

        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_owner(interaction.user):
            await interaction.response.send_message("❌ Test mode: Owner only.", ephemeral=True)
            return

        embed = discord.Embed(
            title="Code Rejected",
            description=(
                f"**Rejected by:** {interaction.user.display_name}\n"
                f"**Full code:** `{self.code}`"
            ),
            color=discord.Color.red(),
        )
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)


class TestTesterView(discord.ui.View):
    """Verify / Flag buttons for a test tester embed."""

    def __init__(self, slot_key: str):
        super().__init__(timeout=AUTO_DELETE_SECONDS)
        self.slot_key = slot_key

    @discord.ui.button(label="Verify", style=discord.ButtonStyle.success)
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_owner(interaction.user):
            await interaction.response.send_message("❌ Test mode: Owner only.", ephemeral=True)
            return

        embed = discord.Embed(
            title="✅ Code Verified",
            description=(
                f"**Verified by:** {interaction.user.display_name}\n"
                f"**Slot:** `{self.slot_key}`"
            ),
            color=discord.Color.green(),
        )
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Flag", style=discord.ButtonStyle.danger)
    async def flag(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_owner(interaction.user):
            await interaction.response.send_message("❌ Test mode: Owner only.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🚩 Code Flagged",
            description=(
                f"**Flagged by:** {interaction.user.display_name}\n"
                f"**Slot:** `{self.slot_key}`"
            ),
            color=discord.Color.red(),
        )
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)


class TestGathererView(discord.ui.View):
    """Gather button for a test gatherer embed."""

    def __init__(self):
        super().__init__(timeout=AUTO_DELETE_SECONDS)

    @discord.ui.button(label="Gather", style=discord.ButtonStyle.primary, emoji="🧬")
    async def gather(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_owner(interaction.user):
            await interaction.response.send_message("❌ Test mode: Owner only.", ephemeral=True)
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

class TestModeCog(commands.Cog, name="TestMode"):
    """Owner-only test mode with manual embed triggers."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Guard ────────────────────────────────────────────────────────

    def _require_test_mode(self, ctx: commands.Context) -> str | None:
        """Return an error message if the caller can't use test commands, else None."""
        if not is_owner(ctx.author):
            return "❌ Only the **Owner** can use test commands."
        if not is_test_mode():
            return "⚠️ Test mode is not active. Use `!test` first."
        return None

    # ── !test ────────────────────────────────────────────────────────

    @commands.command(name="test")
    async def test_cmd(self, ctx: commands.Context):
        """Activate test mode (sandbox)."""
        if not is_owner(ctx.author):
            await ctx.send("❌ Only the **Owner** can toggle test mode.", delete_after=10)
            return

        if is_test_mode():
            await ctx.send("⚠️ Already in test mode. Use `!back` to exit.", delete_after=10)
            return

        enable_test_mode()

        embed = discord.Embed(
            title="🧪 Test Mode — ACTIVE",
            description=(
                "All systems now run in **sandbox mode**.\n\n"
                "**Commands:**\n"
                "`!builder`  — spawn a Builder code embed\n"
                "`!tester`   — spawn a Tester verification embed\n"
                "`!gatherer` — spawn a Gatherer resource embed\n"
                "`!scheduler` — fire a schedule alert\n"
                "`!back`     — exit test mode & clean up\n\n"
                "• Nothing is saved to disk\n"
                "• All embeds auto-delete after **10 minutes**"
            ),
            color=discord.Color.orange(),
        )
        msg = await ctx.send(embed=embed)
        schedule_test_delete(msg)
        log.info("Test mode activated by %s", ctx.author)

    # ── !back ────────────────────────────────────────────────────────

    @commands.command(name="back")
    async def back_cmd(self, ctx: commands.Context):
        """Deactivate test mode and clean up."""
        if not is_owner(ctx.author):
            await ctx.send("❌ Only the **Owner** can toggle test mode.", delete_after=10)
            return

        if not is_test_mode():
            await ctx.send("⚠️ Test mode is not active.", delete_after=10)
            return

        # Delete remaining test messages
        for msg in get_test_messages():
            try:
                await msg.delete()
            except (discord.NotFound, discord.Forbidden):
                pass

        disable_test_mode()

        embed = discord.Embed(
            title="✅ Test Mode — OFF",
            description="All systems returned to **normal operation**.",
            color=discord.Color.green(),
        )
        await ctx.send(embed=embed, delete_after=30)
        log.info("Test mode deactivated by %s", ctx.author)

    # ── !builder ─────────────────────────────────────────────────────

    @commands.command(name="builder")
    async def builder_cmd(self, ctx: commands.Context):
        """Spawn a test Builder code embed."""
        err = self._require_test_mode(ctx)
        if err:
            await ctx.send(err, delete_after=10)
            return

        code = generate_code()
        embed = discord.Embed(
            title="🔧 New Code Available",
            description=f"```\n{code}\n```",
            color=discord.Color.blurple(),
        )
        embed.set_footer(text="🧪 TEST MODE • Builders: Accept or Reject this code.")

        view = TestBuilderView(code=code)
        msg = await ctx.send(embed=embed, view=view)
        schedule_test_delete(msg)

    # ── !tester ──────────────────────────────────────────────────────

    @commands.command(name="tester")
    async def tester_cmd(self, ctx: commands.Context):
        """Spawn a test Tester verification embed."""
        err = self._require_test_mode(ctx)
        if err:
            await ctx.send(err, delete_after=10)
            return

        data = load_chamber()
        filled = get_filled_slots(data)

        if not filled:
            await ctx.send(
                "⚠️ Test chamber is empty. Use `!builder` and accept a code first.",
                delete_after=10,
            )
            return

        slot_key, slot_data = random.choice(filled)
        original = slot_data["code"]
        mutated = mutate_code(original)

        embed = discord.Embed(
            title="🧪 Test Chamber Code",
            description=f"```\n{original}\n```\n```\n{mutated}\n```",
            color=discord.Color.gold(),
        )
        embed.set_footer(text=f"🧪 TEST MODE • Slot: {slot_key} • Testers: Verify or Flag.")

        view = TestTesterView(slot_key=slot_key)
        msg = await ctx.send(embed=embed, view=view)
        schedule_test_delete(msg)

    # ── !gatherer ────────────────────────────────────────────────────

    @commands.command(name="gatherer")
    async def gatherer_cmd(self, ctx: commands.Context):
        """Spawn a test Gatherer resource embed."""
        err = self._require_test_mode(ctx)
        if err:
            await ctx.send(err, delete_after=10)
            return

        num_a = random.randint(1, 485)
        num_b = random.randint(1, 117)

        embed = discord.Embed(
            title="🧬 Resource Alert",
            description=f"🧬 **{num_a}-{num_b}** has died",
            color=discord.Color.dark_purple(),
        )
        embed.set_footer(text="🧪 TEST MODE • Gatherers: Click the button below to gather.")

        view = TestGathererView()
        msg = await ctx.send(embed=embed, view=view)
        schedule_test_delete(msg)

    # ── !scheduler ───────────────────────────────────────────────────

    @commands.command(name="scheduler")
    async def scheduler_cmd(self, ctx: commands.Context):
        """Fire a test schedule start alert (with random outage line)."""
        err = self._require_test_mode(ctx)
        if err:
            await ctx.send(err, delete_after=10)
            return

        outage_line = random.choice(OUTAGE_MESSAGES)
        content = f"🧪 **[TEST]** {outage_line}\n@here, Get back to work to your assigned roles."

        msg = await ctx.send(
            content,
            allowed_mentions=discord.AllowedMentions.none(),  # don't actually ping
        )
        schedule_test_delete(msg)


# ── Setup ────────────────────────────────────────────────────────────

async def setup(bot: commands.Bot):
    await bot.add_cog(TestModeCog(bot))
