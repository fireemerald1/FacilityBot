"""
Verification System – 3-hour onboarding for new members.

• On join: starts a 3-hour window and schedules a word challenge at a random time.
• User can /c immediately — verification runs in parallel.
• At the random time, bot DMs a word to type back.
• After correct response + 3h elapsed: role selection buttons via DM.
• Leave + rejoin: full reset.
"""

import json
import os
import random
import asyncio
import logging
import string
from datetime import datetime, timezone, timedelta

import discord
from discord.ext import commands, tasks

import config

log = logging.getLogger("facility.verification")

# ── Word pool for challenges ────────────────────────────────────────

CHALLENGE_WORDS = [
    "CARBON", "PRISM", "VAULT", "EMBER", "STATIC",
    "SIGMA", "DRIFT", "PULSE", "NEXUS", "OXIDE",
    "FLARE", "DELTA", "COMET", "RAZOR", "TITAN",
    "HELIX", "FROST", "BRAVO", "SOLAR", "GHOST",
    "ALLOY", "QUAKE", "BLAZE", "ORBIT", "SHADE",
    "SURGE", "CRYPT", "OMEGA", "VIVID", "STORM",
]


# ── Persistence ──────────────────────────────────────────────────────

def _load_verify() -> dict:
    if os.path.exists(config.VERIFY_FILE):
        with open(config.VERIFY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_verify(data: dict) -> None:
    with open(config.VERIFY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── Role selection view ──────────────────────────────────────────────

class RoleSelectView(discord.ui.View):
    """Buttons to pick a work role after verification."""

    def __init__(self):
        super().__init__(timeout=300)  # 5-minute timeout

    async def _assign_role(
        self, interaction: discord.Interaction, role_name: str, role_id: int
    ):
        guild = None
        for g in interaction.client.guilds:
            member = g.get_member(interaction.user.id)
            if member:
                guild = g
                break

        if guild is None:
            await interaction.response.send_message(
                "Could not find you in the facility.", ephemeral=True
            )
            return

        role = guild.get_role(role_id)
        if role is None:
            await interaction.response.send_message(
                "Role not found. Contact a supervisor.", ephemeral=True
            )
            return

        member = guild.get_member(interaction.user.id)
        try:
            await member.add_roles(role, reason="Post-verification role selection")
        except Exception as exc:
            log.warning("Failed to assign role: %s", exc)
            await interaction.response.send_message(
                "Failed to assign role. Contact a supervisor.", ephemeral=True
            )
            return

        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content=f"Assigned to **{role_name}**. Report to your station.",
            view=self,
        )
        log.info("Verified user %s selected role: %s", interaction.user, role_name)

    @discord.ui.button(label="Tester", style=discord.ButtonStyle.secondary)
    async def pick_tester(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._assign_role(interaction, "Tester", config.ROLE_TESTER)

    @discord.ui.button(label="Gatherer", style=discord.ButtonStyle.secondary)
    async def pick_gatherer(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._assign_role(interaction, "Gatherer", config.ROLE_GATHERER)

    @discord.ui.button(label="Builder", style=discord.ButtonStyle.secondary)
    async def pick_builder(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._assign_role(interaction, "Builder", config.ROLE_BUILDER)


# ── Cog ──────────────────────────────────────────────────────────────

class VerificationCog(commands.Cog, name="Verification"):
    """Handles new-member verification and role assignment."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Track pending tasks per user so we can cancel on leave
        self._pending_tasks: dict[int, asyncio.Task] = {}

    async def cog_load(self):
        # Resume any pending verifications from before restart
        self._resume_pending.start()

    async def cog_unload(self):
        self._resume_pending.cancel()
        for task in self._pending_tasks.values():
            task.cancel()

    @tasks.loop(count=1)
    async def _resume_pending(self):
        """On startup, reschedule challenges for users still in verification."""
        await self.bot.wait_until_ready()
        data = _load_verify()
        now = datetime.now(timezone.utc)

        for uid_str, info in list(data.items()):
            uid = int(uid_str)
            if info.get("verified"):
                # Check if 3h has passed — send role selection
                joined = datetime.fromisoformat(info["joined_at"])
                hours = config.VERIFICATION_HOURS
                if now >= joined + timedelta(hours=hours):
                    asyncio.create_task(self._send_role_selection(uid))
                continue

            # Not verified — reschedule challenge
            if not info.get("challenge_sent_at"):
                sched_time = datetime.fromisoformat(info["challenge_scheduled_at"])
                delay = (sched_time - now).total_seconds()
                if delay <= 0:
                    delay = 5  # send soon
                self._pending_tasks[uid] = asyncio.create_task(
                    self._challenge_flow(uid, delay)
                )

    # ── Member join ──────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        hours = config.VERIFICATION_HOURS
        now = datetime.now(timezone.utc)

        # Random time within the verification window
        challenge_delay_s = random.randint(60, int(hours * 3600) - 60)
        challenge_time = now + timedelta(seconds=challenge_delay_s)
        word = random.choice(CHALLENGE_WORDS)

        data = _load_verify()
        data[str(member.id)] = {
            "joined_at": now.isoformat(),
            "challenge_word": word,
            "challenge_sent_at": None,
            "challenge_scheduled_at": challenge_time.isoformat(),
            "verified": False,
        }
        _save_verify(data)

        # Schedule the challenge
        self._pending_tasks[member.id] = asyncio.create_task(
            self._challenge_flow(member.id, challenge_delay_s)
        )

        log.info(
            "Verification started for %s. Challenge in %d minutes.",
            member, challenge_delay_s // 60,
        )

    # ── Member leave — cleanup ───────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        # Cancel pending task
        task = self._pending_tasks.pop(member.id, None)
        if task:
            task.cancel()

        # Remove from verification data
        data = _load_verify()
        if str(member.id) in data:
            data.pop(str(member.id))
            _save_verify(data)

        log.info("Verification cleared for %s (left server).", member)

    # ── Challenge flow ───────────────────────────────────────────────

    async def _challenge_flow(self, user_id: int, delay_s: float):
        """Wait, then DM the challenge word."""
        await asyncio.sleep(delay_s)

        data = _load_verify()
        uid = str(user_id)
        if uid not in data or data[uid].get("verified"):
            return

        # Find the user
        user = self.bot.get_user(user_id)
        if user is None:
            try:
                user = await self.bot.fetch_user(user_id)
            except Exception:
                log.warning("Could not find user %s for challenge.", user_id)
                return

        word = data[uid]["challenge_word"]

        try:
            await user.send(
                f"**Verification required.**\n"
                f"Type the following word exactly: `{word}`"
            )
            data[uid]["challenge_sent_at"] = datetime.now(timezone.utc).isoformat()
            _save_verify(data)
            log.info("Sent challenge word to user %s.", user_id)
        except discord.Forbidden:
            log.warning("Cannot DM user %s for verification challenge.", user_id)

    # ── Listen for DM responses ──────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Only care about DMs from non-bots
        if message.guild is not None:
            return
        if message.author.bot:
            return

        data = _load_verify()
        uid = str(message.author.id)

        if uid not in data:
            return

        info = data[uid]
        if info.get("verified"):
            return
        if not info.get("challenge_sent_at"):
            return  # challenge not sent yet

        # Check the word
        if message.content.strip().upper() == info["challenge_word"]:
            info["verified"] = True
            _save_verify(data)

            await message.reply("Verification complete.")
            log.info("User %s verified successfully.", message.author.id)

            # Check if 3h has passed
            joined = datetime.fromisoformat(info["joined_at"])
            hours = config.VERIFICATION_HOURS
            remaining = (joined + timedelta(hours=hours)) - datetime.now(timezone.utc)

            if remaining.total_seconds() <= 0:
                # Time already passed — send role selection now
                await self._send_role_selection(message.author.id)
            else:
                # Schedule role selection for when the window ends
                asyncio.create_task(
                    self._delayed_role_selection(message.author.id, remaining.total_seconds())
                )
        else:
            await message.reply("Incorrect. Try again.")

    # ── Role selection ───────────────────────────────────────────────

    async def _delayed_role_selection(self, user_id: int, delay_s: float):
        await asyncio.sleep(delay_s)
        await self._send_role_selection(user_id)

    async def _send_role_selection(self, user_id: int):
        """DM the user with role selection buttons."""
        user = self.bot.get_user(user_id)
        if user is None:
            try:
                user = await self.bot.fetch_user(user_id)
            except Exception:
                return

        try:
            await user.send(
                "Verification window complete. Select your station:",
                view=RoleSelectView(),
            )
            log.info("Sent role selection to user %s.", user_id)
        except discord.Forbidden:
            log.warning("Cannot DM user %s for role selection.", user_id)

        # Clean up verification data
        data = _load_verify()
        data.pop(str(user_id), None)
        _save_verify(data)


# ── Setup ────────────────────────────────────────────────────────────

async def setup(bot: commands.Bot):
    await bot.add_cog(VerificationCog(bot))
