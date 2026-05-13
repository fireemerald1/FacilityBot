"""
Role Selection & Promotion – manages work assignments and promotions.

• !pick    → shows buttons to select Tester, Gatherer, or Builder.
• !promote → Boss-only. Promotes a staff member to supervisor.
• First pick is immediate. Role changes require a 2-week cooldown.
• Only one work role at a time.
"""

import json
import os
import logging
from datetime import datetime, timezone, timedelta

import discord
from discord.ext import commands

import config
from utils.permissions import is_boss

log = logging.getLogger("facility.roles")

WORK_ROLES = {
    "tester": config.ROLE_TESTER,
    "gatherer": config.ROLE_GATHERER,
    "builder": config.ROLE_BUILDER,
}

# Maps work role ID → supervisor role ID
SUPERVISOR_MAP = {
    config.ROLE_TESTER: config.ROLE_SUPERVISOR_TESTER,
    config.ROLE_GATHERER: config.ROLE_SUPERVISOR_GATHERER,
    config.ROLE_BUILDER: config.ROLE_SUPERVISOR_BUILDER,
}

# Maps supervisor role ID → display name
SUPERVISOR_NAMES = {
    config.ROLE_SUPERVISOR_TESTER: "Tester Supervisor",
    config.ROLE_SUPERVISOR_GATHERER: "Gatherer Supervisor",
    config.ROLE_SUPERVISOR_BUILDER: "Builder Supervisor",
}


# ── Pick storage ─────────────────────────────────────────────────────

def _load_picks() -> dict:
    if not os.path.exists(config.PICK_FILE):
        return {}
    with open(config.PICK_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_picks(data: dict) -> None:
    with open(config.PICK_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _get_last_pick(user_id: int) -> str | None:
    """Return ISO timestamp of last pick, or None."""
    data = _load_picks()
    return data.get(str(user_id))


def _set_last_pick(user_id: int) -> None:
    data = _load_picks()
    data[str(user_id)] = datetime.now(timezone.utc).isoformat()
    _save_picks(data)


# ── Helpers ──────────────────────────────────────────────────────────

def _get_current_work_role(member: discord.Member) -> int | None:
    """Return the role ID of the member's current work role, or None."""
    member_role_ids = {r.id for r in member.roles}
    for role_id in WORK_ROLES.values():
        if role_id in member_role_ids:
            return role_id
    return None


def _has_any_work_role(member: discord.Member) -> bool:
    return _get_current_work_role(member) is not None


# ── View ─────────────────────────────────────────────────────────────

class PickView(discord.ui.View):
    """Three buttons for role selection."""

    def __init__(self):
        super().__init__(timeout=120)

    async def _handle_pick(
        self, interaction: discord.Interaction, role_name: str
    ) -> None:
        member = interaction.user
        target_role_id = WORK_ROLES[role_name]
        current_role_id = _get_current_work_role(member)

        # Already has the same role
        if current_role_id == target_role_id:
            await interaction.response.send_message(
                f"You are already assigned as {role_name}.",
                ephemeral=True,
            )
            return

        # Has a role → check cooldown
        if current_role_id is not None:
            last_pick_iso = _get_last_pick(member.id)
            if last_pick_iso:
                last_pick = datetime.fromisoformat(last_pick_iso)
                elapsed = datetime.now(timezone.utc) - last_pick
                required = timedelta(days=config.ROLE_PICK_COOLDOWN_DAYS)
                if elapsed < required:
                    remaining = required - elapsed
                    days_left = remaining.days
                    hours_left = remaining.seconds // 3600
                    await interaction.response.send_message(
                        f"Role reassignment denied. Cooldown active: {days_left}d {hours_left}h remaining.",
                        ephemeral=True,
                    )
                    return

        guild = interaction.guild

        # Remove old work role if present
        if current_role_id is not None:
            old_role = guild.get_role(current_role_id)
            if old_role:
                try:
                    await member.remove_roles(old_role, reason="Role reassignment via !pick")
                except Exception as exc:
                    log.warning("Failed to remove role %s from %s: %s", current_role_id, member, exc)

        # Add new role
        new_role = guild.get_role(target_role_id)
        if new_role is None:
            await interaction.response.send_message(
                "Role not found in this server. Contact a supervisor.",
                ephemeral=True,
            )
            return

        try:
            await member.add_roles(new_role, reason="Role selected via !pick")
        except Exception as exc:
            log.warning("Failed to add role %s to %s: %s", target_role_id, member, exc)
            await interaction.response.send_message(
                "Failed to assign role. Contact a supervisor.",
                ephemeral=True,
            )
            return

        # Record the pick timestamp
        _set_last_pick(member.id)

        # Disable all buttons after selection
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(view=self)

        # Confirm
        if current_role_id is not None:
            msg = f"{member.display_name} has been reassigned to {role_name}."
        else:
            msg = f"{member.display_name} has been assigned to {role_name}."

        await interaction.followup.send(msg, ephemeral=True)
        log.info("User %s picked role: %s", member, role_name)

    @discord.ui.button(label="Tester", style=discord.ButtonStyle.secondary)
    async def pick_tester(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_pick(interaction, "tester")

    @discord.ui.button(label="Gatherer", style=discord.ButtonStyle.secondary)
    async def pick_gatherer(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_pick(interaction, "gatherer")

    @discord.ui.button(label="Builder", style=discord.ButtonStyle.secondary)
    async def pick_builder(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_pick(interaction, "builder")


# ── Cog ──────────────────────────────────────────────────────────────

class RolesCog(commands.Cog, name="Roles"):
    """Handles work-role selection and promotion."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="pick")
    async def pick_cmd(self, ctx: commands.Context):
        """Select your work assignment."""
        embed = discord.Embed(
            title="Role Assignment",
            description="Select your station. You may only hold one work role at a time.",
            color=discord.Color.dark_grey(),
        )
        embed.set_footer(text="Role changes are subject to a 14-day cooldown.")

        view = PickView()
        await ctx.send(embed=embed, view=view)

    @commands.command(name="promote")
    async def promote_cmd(self, ctx: commands.Context, member: discord.Member):
        """Promote a staff member to supervisor. Boss only."""
        if not is_boss(ctx.author):
            await ctx.send("Access denied. Boss clearance required.", delete_after=10)
            return

        # Determine the member's current work role
        current_role_id = _get_current_work_role(member)
        if current_role_id is None:
            await ctx.send(
                f"{member.display_name} has no work role assigned. Cannot promote.",
                delete_after=10,
            )
            return

        # Check if a supervisor role exists for their work role
        supervisor_role_id = SUPERVISOR_MAP.get(current_role_id)
        if supervisor_role_id is None:
            await ctx.send("No supervisor role mapped for this position.", delete_after=10)
            return

        # Check if already a supervisor
        if any(r.id == supervisor_role_id for r in member.roles):
            await ctx.send(
                f"{member.display_name} already holds this supervisor position.",
                delete_after=10,
            )
            return

        guild = ctx.guild
        supervisor_role = guild.get_role(supervisor_role_id)
        if supervisor_role is None:
            await ctx.send("Supervisor role not found in this server.", delete_after=10)
            return

        try:
            await member.add_roles(supervisor_role, reason=f"Promoted by {ctx.author}")
        except Exception as exc:
            log.warning("Failed to promote %s: %s", member, exc)
            await ctx.send("Promotion failed. Check bot permissions.", delete_after=10)
            return

        title = SUPERVISOR_NAMES.get(supervisor_role_id, "Supervisor")
        log.info("%s promoted %s to %s", ctx.author, member, title)

        # Announce in promotion channel
        promo_channel = self.bot.get_channel(config.CHANNEL_PROMOTION)
        if promo_channel:
            announcement = f"user_{member.id} has been promoted to {title}."
            try:
                await promo_channel.send(
                    announcement,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except Exception as exc:
                log.warning("Failed to send promotion announcement: %s", exc)

        await ctx.send(f"{member.display_name} has been promoted to {title}.", delete_after=15)

    @promote_cmd.error
    async def promote_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("Usage: `!promote @user`", delete_after=10)
        elif isinstance(error, commands.MemberNotFound):
            await ctx.send("Member not found.", delete_after=10)


# ── Setup ────────────────────────────────────────────────────────────

async def setup(bot: commands.Bot):
    await bot.add_cog(RolesCog(bot))
