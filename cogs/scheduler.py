"""
Scheduler System – controls the active window for the Facility bot.

• Active: Saturday & Sunday, 05:00–17:00 UTC only.
• At 05:00 UTC sends an @here alert; if late (>=5 min) sends a random outage line.
• At 17:00 UTC disables all active work-system embeds and stops loops.
• On new-week transition, disables ALL lingering buttons from previous sessions.
• Persists state to schedule-state.json so docker restarts don't duplicate alerts.
• On startup, restarts work-cog loops if inside the active window.
"""

import random
import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks

from config import (
    CHANNEL_ALERT,
    CHANNEL_BUILDER,
    CHANNEL_TESTER,
    CHANNEL_GATHERER,
    CHANNEL_GENERAL_STAFF,
    CHANNEL_MEDIA,
    ACTIVE_DAYS,
    ACTIVE_START_HOUR,
    ACTIVE_END_HOUR,
    LATE_THRESHOLD_MINUTES,
    SCHEDULE_CHECK_INTERVAL_S,
    OUTAGE_MESSAGES,
    SHIFT_END_MESSAGES,
)
from utils.schedule import (
    is_within_active_window,
    load_schedule_state,
    save_schedule_state,
    iso_week,
)
from teststate import is_test_mode

log = logging.getLogger("facility.scheduler")


class SchedulerCog(commands.Cog, name="Scheduler"):
    """Manages active-window alerts and shutdown."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._start_sent = False     # True after 05:00 alert sent this window
        self._shutdown_done = False  # True after 17:00 shutdown this window
        self._week_cleaned = False   # True after new-week button cleanup

    # ── Lifecycle ────────────────────────────────────────────────────

    async def cog_load(self):
        self.schedule_loop.start()

    async def cog_unload(self):
        self.schedule_loop.cancel()

    # ── Main loop ────────────────────────────────────────────────────

    @tasks.loop(seconds=SCHEDULE_CHECK_INTERVAL_S)
    async def schedule_loop(self):
        if is_test_mode():
            return  # testmode cog handles the cycle
        now = datetime.now(timezone.utc)
        today_weekday = now.weekday()
        is_active_day = today_weekday in ACTIVE_DAYS
        current_week = iso_week(now)

        state = load_schedule_state()

        # ── New-week cleanup ─────────────────────────────────────────
        last_week = state.get("last_active_week")
        if last_week and last_week != current_week and not self._week_cleaned:
            await self._disable_all_channel_buttons()
            self._week_cleaned = True
            state["last_active_week"] = current_week
            save_schedule_state(state)
            log.info("New week (%s -> %s). Disabled old buttons.", last_week, current_week)

        if not is_active_day:
            # Reset flags for next active day
            self._start_sent = False
            self._shutdown_done = False
            return

        # Record the current week as active
        if state.get("last_active_week") != current_week:
            state["last_active_week"] = current_week
            self._week_cleaned = False
            save_schedule_state(state)

        # ── 05:00 UTC start alert ────────────────────────────────────
        if now.hour >= ACTIVE_START_HOUR and now.hour < ACTIVE_END_HOUR and not self._start_sent:
            last_alert_date = state.get("last_alert_date")
            today_str = now.strftime("%Y-%m-%d")

            if last_alert_date != today_str:
                minutes_past = (now.hour - ACTIVE_START_HOUR) * 60 + now.minute
                is_late = minutes_past >= LATE_THRESHOLD_MINUTES
                await self._send_start_alert(is_late)

                state["last_alert_date"] = today_str
                save_schedule_state(state)

            # Ensure work-cog loops are running (handles startup mid-window)
            self._ensure_work_loops_running()
            await self._lock_channels()
            self._start_sent = True

        # ── 17:00 UTC shutdown ───────────────────────────────────────
        if now.hour >= ACTIVE_END_HOUR and not self._shutdown_done:
            await self._do_shutdown()
            self._shutdown_done = True

    @schedule_loop.before_loop
    async def _wait_ready(self):
        await self.bot.wait_until_ready()

    # ── Alert messages ───────────────────────────────────────────────

    async def _send_start_alert(self, is_late: bool) -> None:
        channel = self.bot.get_channel(CHANNEL_ALERT)
        if channel is None:
            log.warning("Alert channel not found.")
            return

        if is_late:
            outage_line = random.choice(OUTAGE_MESSAGES)
            content = f"{outage_line}\n@here, return to your assigned stations."
        else:
            content = "@here, return to your assigned stations."

        await channel.send(content, allowed_mentions=discord.AllowedMentions(everyone=True))
        log.info("Sent %s start alert.", "late" if is_late else "on-time")

    # ── Channel locking ──────────────────────────────────────────────

    async def _lock_channels(self) -> None:
        """Remove send_messages for @everyone in general-staff and media."""
        for ch_id in (CHANNEL_GENERAL_STAFF, CHANNEL_MEDIA):
            channel = self.bot.get_channel(ch_id)
            if channel is None:
                continue
            try:
                overwrite = channel.overwrites_for(channel.guild.default_role)
                overwrite.send_messages = False
                await channel.set_permissions(
                    channel.guild.default_role, overwrite=overwrite,
                    reason="Work shift started — channel locked.",
                )
                log.info("Locked channel %s.", channel.name)
            except Exception as exc:
                log.warning("Failed to lock %s: %s", ch_id, exc)

    async def _unlock_channels(self) -> None:
        """Restore send_messages for @everyone in general-staff and media."""
        for ch_id in (CHANNEL_GENERAL_STAFF, CHANNEL_MEDIA):
            channel = self.bot.get_channel(ch_id)
            if channel is None:
                continue
            try:
                overwrite = channel.overwrites_for(channel.guild.default_role)
                overwrite.send_messages = None   # reset to default
                await channel.set_permissions(
                    channel.guild.default_role, overwrite=overwrite,
                    reason="Work shift ended — channel unlocked.",
                )
                log.info("Unlocked channel %s.", channel.name)
            except Exception as exc:
                log.warning("Failed to unlock %s: %s", ch_id, exc)

    # ── Ensure work loops are running ────────────────────────────────

    def _ensure_work_loops_running(self) -> None:
        """Restart work-cog loops if they were stopped (e.g. after shutdown or restart)."""
        loop_map = {
            "Builder": "builder_loop",
            "Tester": "tester_loop",
            "Gatherer": "gatherer_loop",
        }
        for cog_name, loop_attr in loop_map.items():
            cog = self.bot.cogs.get(cog_name)
            if cog is None:
                continue
            loop = getattr(cog, loop_attr, None)
            if loop and not loop.is_running():
                loop.start()
                log.info("Started %s loop.", cog_name)

    # ── Shutdown ─────────────────────────────────────────────────────

    async def _do_shutdown(self) -> None:
        """Disable active embeds in all work channels, stop cog loops, unlock channels."""
        log.info("17:00 UTC shutdown — disabling active embeds.")

        # Disable buttons in all three work channels
        for ch_id in (CHANNEL_BUILDER, CHANNEL_TESTER, CHANNEL_GATHERER):
            channel = self.bot.get_channel(ch_id)
            if channel is None:
                continue
            try:
                async for message in channel.history(limit=50):
                    if message.author == self.bot.user and message.components:
                        view = discord.ui.View.from_message(message)
                        for child in view.children:
                            child.disabled = True
                        await message.edit(view=view)
            except Exception as exc:
                log.warning("Error disabling buttons in %s: %s", ch_id, exc)

        # Stop the work-system loops and clear their tracking
        loop_map = {
            "Builder": "builder_loop",
            "Tester": "tester_loop",
            "Gatherer": "gatherer_loop",
        }
        for cog_name, loop_attr in loop_map.items():
            cog = self.bot.cogs.get(cog_name)
            if cog is None:
                continue
            if hasattr(cog, "_active_ids"):
                cog._active_ids.clear()
            loop = getattr(cog, loop_attr, None)
            if loop and loop.is_running():
                loop.cancel()
                log.info("Stopped %s loop.", cog_name)

        # Send shift-end message to general-staff and media before unlocking
        await self._send_shift_end_message()

        # Unlock general-staff and media
        await self._unlock_channels()

    # ── Shift-end announcement ────────────────────────────────────────

    async def _send_shift_end_message(self) -> None:
        """Send a lore-themed end-of-shift message to the alert channel."""
        message_text = random.choice(SHIFT_END_MESSAGES)
        channel = self.bot.get_channel(CHANNEL_ALERT)
        if channel is None:
            log.warning("Alert channel not found for shift-end message.")
            return
        try:
            await channel.send(message_text)
            log.info("Sent shift-end message to %s.", channel.name)
        except Exception as exc:
            log.warning("Failed to send shift-end message to %s: %s", channel.name, exc)

    # ── New-week button cleanup ──────────────────────────────────────

    async def _disable_all_channel_buttons(self) -> None:
        """Scan work channels and disable every button the bot owns."""
        for ch_id in (CHANNEL_BUILDER, CHANNEL_TESTER, CHANNEL_GATHERER):
            channel = self.bot.get_channel(ch_id)
            if channel is None:
                continue
            try:
                async for message in channel.history(limit=200):
                    if message.author == self.bot.user and message.components:
                        view = discord.ui.View.from_message(message)
                        for child in view.children:
                            child.disabled = True
                        await message.edit(view=view)
            except Exception as exc:
                log.warning("Week-cleanup error in %s: %s", ch_id, exc)
        log.info("Disabled all old-week buttons.")


# ── Setup ────────────────────────────────────────────────────────────

async def setup(bot: commands.Bot):
    await bot.add_cog(SchedulerCog(bot))
