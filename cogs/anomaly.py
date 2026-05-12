"""
Anomaly System – AI test subjects that escape during shifts.

• During active shifts, 1/n chance per hour an anomaly spawns.
• Anomaly gets a #XXXXX# identity + color (indistinguishable from real users).
• Chats via Gemini AI with one of 10 random personalities.
• Gatherers contain anomalies with /gather <id>.
• Misidentifying a real user penalises both parties and notifies the boss.
• Uncontained anomalies escape after a timeout (alert sent).
• !anomaly forces an immediate spawn (Boss only).
"""

import os
import random
import asyncio
import logging
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import (
    ANOMALY_CHANNELS,
    CHANNEL_PURPOSES,
    CHANNEL_ALERT,
    ROLE_OWNER,
)
from cogs.chat import (
    get_identity,
    get_identity_by_id_number,
    get_or_create_webhook,
    avatar_url_for,
)
from cogs.settings import get_setting
from utils.permissions import is_gatherer, is_boss
from utils.schedule import is_within_active_window

log = logging.getLogger("facility.anomaly")

# ── Gemini setup ─────────────────────────────────────────────────────

_genai = None
_model = None


def _ensure_genai():
    """Lazy-init the Gemini client."""
    global _genai, _model
    if _model is not None:
        return
    try:
        import google.generativeai as genai
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        _model = genai.GenerativeModel("gemini-2.5-flash")
        _genai = genai
        log.info("Gemini model initialised.")
    except Exception as exc:
        log.error("Failed to initialise Gemini: %s", exc)


# ── Personalities ────────────────────────────────────────────────────

PERSONALITIES = [
    {
        "name": "The Quiet One",
        "prompt": (
            "You are a very quiet, introverted person. You use lowercase only, "
            "give short minimal responses (3-8 words), rarely ask questions, "
            "and seem disinterested. You don't use punctuation much."
        ),
    },
    {
        "name": "The Overthinker",
        "prompt": (
            "You are an anxious overthinker. You ramble, second-guess yourself, "
            "add qualifiers like 'I think' and 'maybe', and ask follow-up questions. "
            "You sometimes correct yourself mid-sentence."
        ),
    },
    {
        "name": "The Joker",
        "prompt": (
            "You are a class clown type. You try to be funny, use sarcasm and "
            "wordplay, deflect serious topics with humor, and drop casual jokes. "
            "You're never mean, just playful."
        ),
    },
    {
        "name": "The Newbie",
        "prompt": (
            "You are brand new and confused. You ask lots of basic questions, "
            "seem lost about how things work, are overly polite, and say things "
            "like 'sorry if this is a dumb question'. You're eager to fit in."
        ),
    },
    {
        "name": "The Veteran",
        "prompt": (
            "You talk like you've been here forever. You reference 'the old days', "
            "compare things to how they used to be, give unsolicited advice, and "
            "act a bit jaded but caring. You use phrases like 'back when I started'."
        ),
    },
    {
        "name": "The Paranoid",
        "prompt": (
            "You are deeply suspicious of everything. You question motives, "
            "read into things that aren't there, trust no one, and make vague "
            "ominous comments. You say things like 'that's what they want you to think'."
        ),
    },
    {
        "name": "The Friendly",
        "prompt": (
            "You are warm, supportive, and positive. You greet everyone, "
            "encourage people, use the occasional emoji, and always look "
            "on the bright side. You're the kind of person everyone likes."
        ),
    },
    {
        "name": "The Cold",
        "prompt": (
            "You are blunt, clinical, and emotionless. You speak in short, "
            "factual statements. No small talk. No pleasantries. You sound "
            "almost robotic but you're human. You don't ask questions."
        ),
    },
    {
        "name": "The Curious",
        "prompt": (
            "You are endlessly curious. You ask about everything — how things work, "
            "why people do what they do, what happens next. You get excited about "
            "learning new things and say 'oh interesting' a lot."
        ),
    },
    {
        "name": "The Edgy",
        "prompt": (
            "You have dark humor and make cryptic, slightly unsettling statements. "
            "You're not threatening, just… off. You say things that make people "
            "uncomfortable without being explicit. You're vaguely philosophical."
        ),
    },
]


# ── Active anomaly tracker ──────────────────────────────────────────

class ActiveAnomaly:
    """Tracks a single active anomaly instance."""

    def __init__(
        self,
        identity_name: str,
        color: str,
        channel_id: int,
        personality: dict,
    ):
        self.identity_name = identity_name
        self.color = color
        self.channel_id = channel_id
        self.personality = personality
        self.conversation: list[dict] = []
        self.alive = True
        self.spawned_at = datetime.now(timezone.utc)
        self._timeout_task: asyncio.Task | None = None

    @property
    def id_number(self) -> str:
        """Return just the 5-digit number (e.g. '04271')."""
        return self.identity_name[1:-1]  # strip the # wrappers


# ── Cog ──────────────────────────────────────────────────────────────

class AnomalyCog(commands.Cog, name="Anomaly"):
    """Manages AI anomaly test subjects."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._active: list[ActiveAnomaly] = []
        self._webhook_cache: dict[int, discord.Webhook] = {}

    # ── Lifecycle ────────────────────────────────────────────────────

    async def cog_load(self):
        self.anomaly_loop.start()

    async def cog_unload(self):
        self.anomaly_loop.cancel()
        for a in self._active:
            a.alive = False
            if a._timeout_task:
                a._timeout_task.cancel()

    # ── Webhook helper ───────────────────────────────────────────────

    async def _get_webhook(self, channel: discord.TextChannel) -> discord.Webhook:
        if channel.id not in self._webhook_cache:
            self._webhook_cache[channel.id] = await get_or_create_webhook(channel)
        return self._webhook_cache[channel.id]

    # ── Spawn logic ─────────────────────────────────────────────────

    @tasks.loop(minutes=60)
    async def anomaly_loop(self):
        """Roll for anomaly spawn every hour during active shift."""
        if not is_within_active_window():
            return

        max_active = get_setting("anomaly_max")
        if len(self._active) >= max_active:
            return

        chance_n = get_setting("anomaly_chance")
        roll = random.randint(1, chance_n)
        if roll != 1:
            log.info("Anomaly roll: %d/%d — no spawn.", roll, chance_n)
            return

        await self._spawn_anomaly()

    @anomaly_loop.before_loop
    async def _wait_ready(self):
        await self.bot.wait_until_ready()

    async def _spawn_anomaly(self) -> ActiveAnomaly | None:
        """Create and launch an anomaly."""
        _ensure_genai()
        if _model is None:
            log.warning("Cannot spawn anomaly — Gemini not available.")
            return None

        # Pick a random channel
        ch_id = random.choice(ANOMALY_CHANNELS)
        channel = self.bot.get_channel(ch_id)
        if channel is None:
            log.warning("Anomaly channel %s not found.", ch_id)
            return None

        # Generate unique identity
        num = random.randint(0, 99999)
        name = f"#{num:05d}#"
        color = f"{random.randint(0, 0xFFFFFF):06X}"
        personality = random.choice(PERSONALITIES)

        anomaly = ActiveAnomaly(
            identity_name=name,
            color=color,
            channel_id=ch_id,
            personality=personality,
        )
        self._active.append(anomaly)

        log.info(
            "Anomaly %s spawned in #%s with personality '%s'.",
            name, channel.name, personality["name"],
        )

        # Send first message
        purpose = CHANNEL_PURPOSES.get(ch_id, "a channel in the facility")
        first_prompt = (
            f"{personality['prompt']}\n\n"
            f"You are chatting in a server. The channel is #{channel.name} — {purpose}.\n"
            "Send your first message. Keep it natural and under 2 sentences. "
            "Do NOT mention you are AI. Do NOT use quotation marks around your message."
        )

        try:
            response = await asyncio.to_thread(
                _model.generate_content, first_prompt
            )
            text = response.text.strip().strip('"').strip("'")
        except Exception as exc:
            log.warning("Gemini error on first message: %s", exc)
            text = "hello"

        anomaly.conversation.append({"role": "model", "parts": [text]})

        webhook = await self._get_webhook(channel)
        try:
            await webhook.send(
                content=text,
                username=name,
                avatar_url=avatar_url_for(color),
            )
        except Exception as exc:
            log.warning("Failed to send anomaly message: %s", exc)

        # Start escape timeout
        timeout_minutes = get_setting("anomaly_timeout")
        anomaly._timeout_task = asyncio.create_task(
            self._escape_timer(anomaly, timeout_minutes)
        )

        return anomaly

    async def _escape_timer(self, anomaly: ActiveAnomaly, minutes: int):
        """Kill the anomaly after N minutes if not gathered."""
        await asyncio.sleep(minutes * 60)
        if not anomaly.alive:
            return

        anomaly.alive = False
        self._active.remove(anomaly)

        # Alert
        alert_ch = self.bot.get_channel(CHANNEL_ALERT)
        if alert_ch:
            try:
                await alert_ch.send(
                    f"⚠ Anomaly {anomaly.identity_name} has escaped the facility. "
                    f"Containment failed."
                )
            except Exception as exc:
                log.warning("Failed to send escape alert: %s", exc)

        log.info("Anomaly %s escaped (timeout).", anomaly.identity_name)

    # ── Respond to replies ───────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Respond if someone talks in an anomaly's channel or mentions its name."""
        if message.author.bot and not message.webhook_id:
            return
        if message.guild is None:
            return

        # Find an active anomaly — match by channel OR by name mention
        anomaly = None
        for a in self._active:
            if not a.alive:
                continue
            # Same channel — always respond
            if a.channel_id == message.channel.id:
                anomaly = a
                break
            # Name mentioned in any channel — respond there
            if a.identity_name in message.content:
                anomaly = a
                break

        if anomaly is None:
            return

        # Don't respond to own webhook messages
        if message.webhook_id and message.author.display_name == anomaly.identity_name:
            return

        # Build context
        _ensure_genai()
        if _model is None:
            return

        purpose = CHANNEL_PURPOSES.get(anomaly.channel_id, "a channel")
        context_parts = []

        # Get the replied-to message if any
        if message.reference and message.reference.message_id:
            try:
                ref_msg = await message.channel.fetch_message(message.reference.message_id)
                context_parts.append(f"[They replied to a message that said: \"{ref_msg.content}\"]")
            except Exception:
                pass

        context_parts.append(f"[Someone said: \"{message.content}\"]")

        reply_prompt = (
            f"{anomaly.personality['prompt']}\n\n"
            f"You are chatting in #{message.channel.name} — {purpose}.\n"
            f"Stay in character. Keep responses natural and under 2 sentences.\n"
            f"Do NOT mention you are AI. Do NOT use quotation marks around your response.\n\n"
            + "\n".join(context_parts)
            + "\n\nRespond:"
        )

        try:
            response = await asyncio.to_thread(
                _model.generate_content, reply_prompt
            )
            text = response.text.strip().strip('"').strip("'")
        except Exception as exc:
            log.warning("Gemini error on reply: %s", exc)
            return

        anomaly.conversation.append({"role": "model", "parts": [text]})

        # Small delay to feel natural
        await asyncio.sleep(random.uniform(2.0, 6.0))

        if not anomaly.alive:
            return

        try:
            webhook = await self._get_webhook(message.channel)
            await webhook.send(
                content=text,
                username=anomaly.identity_name,
                avatar_url=avatar_url_for(anomaly.color),
            )
        except Exception as exc:
            log.warning("Failed to send anomaly reply: %s", exc)

    # ── /gather slash command ────────────────────────────────────────

    @app_commands.command(
        name="gather",
        description="Contain an anomaly by its 5-digit ID.",
    )
    @app_commands.describe(id="The 5-digit ID number (e.g. 04271)")
    async def gather_command(self, interaction: discord.Interaction, id: str):
        """Attempt to contain an anomaly."""
        if not is_gatherer(interaction.user):
            await interaction.response.send_message(
                "Access denied. Gatherer clearance required.",
                ephemeral=True,
            )
            return

        # Normalise to 5 digits
        id_clean = id.strip().lstrip("#").rstrip("#").zfill(5)

        # Check if it's an active anomaly
        target_anomaly = None
        for a in self._active:
            if a.id_number == id_clean and a.alive:
                target_anomaly = a
                break

        # Check if it's a real user
        real_user_id = None
        if target_anomaly is None:
            real_user_id = get_identity_by_id_number(id_clean)

        if target_anomaly is None and real_user_id is None:
            await interaction.response.send_message(
                f"No subject found with ID `{id_clean}`.",
                ephemeral=True,
            )
            return

        # ── Same response regardless of outcome ─────────────────────
        await interaction.response.send_message(
            f"Containment order submitted for `#{id_clean}#`. Processing...",
            ephemeral=True,
        )

        log.info(
            "Gather submitted by %s for #%s# — result pending (3 min).",
            interaction.user, id_clean,
        )

        # Schedule the delayed result
        asyncio.create_task(
            self._delayed_gather_result(
                interaction=interaction,
                id_clean=id_clean,
                target_anomaly=target_anomaly,
                real_user_id=real_user_id,
            )
        )

    async def _delayed_gather_result(
        self,
        interaction: discord.Interaction,
        id_clean: str,
        target_anomaly: ActiveAnomaly | None,
        real_user_id: int | None,
    ):
        """Wait 3 minutes, then execute the actual gather outcome."""
        await asyncio.sleep(180)  # 3 minutes

        if target_anomaly is not None:
            # ── Successful containment ──────────────────────────────
            if target_anomaly.alive:
                target_anomaly.alive = False
                if target_anomaly._timeout_task:
                    target_anomaly._timeout_task.cancel()
                try:
                    self._active.remove(target_anomaly)
                except ValueError:
                    pass

            # DM the gatherer — success
            try:
                await interaction.user.send(
                    f"Containment confirmed. Anomaly `#{id_clean}#` has been neutralised."
                )
            except discord.Forbidden:
                pass

            log.info(
                "Anomaly %s contained by %s (after 3-min delay).",
                target_anomaly.identity_name, interaction.user,
            )

        elif real_user_id is not None:
            # ── Misidentification ───────────────────────────────────
            guild = interaction.guild
            target_member = guild.get_member(real_user_id) if guild else None

            # Mute the target
            misid_target_mins = get_setting("mute_misid_target")
            if target_member:
                try:
                    until = discord.utils.utcnow() + timedelta(
                        minutes=misid_target_mins
                    )
                    await target_member.timeout(
                        until,
                        reason="Misidentified as anomaly by a gatherer.",
                    )
                except discord.Forbidden:
                    pass

            # Mute the gatherer
            misid_gatherer_mins = get_setting("mute_misid_gatherer")
            gatherer = guild.get_member(interaction.user.id) if guild else None
            if gatherer:
                try:
                    until = discord.utils.utcnow() + timedelta(
                        minutes=misid_gatherer_mins
                    )
                    await gatherer.timeout(
                        until,
                        reason="Misidentified a staff member as an anomaly.",
                    )
                except discord.Forbidden:
                    pass

            # DM the gatherer — failure
            try:
                await interaction.user.send(
                    f"Misidentification detected. You targeted a staff member "
                    f"(`#{id_clean}#`). Exercise caution. "
                    f"Mute duration: {misid_gatherer_mins} minutes."
                )
            except discord.Forbidden:
                pass

            # DM the boss
            if guild:
                for member in guild.members:
                    if any(r.id == ROLE_OWNER for r in member.roles):
                        try:
                            await member.send(
                                f"**Incident report:** {interaction.user.display_name} "
                                f"misidentified `#{id_clean}#` "
                                f"({target_member.display_name if target_member else 'unknown'}) "
                                f"as an anomaly in #{interaction.channel.name}."
                            )
                        except discord.Forbidden:
                            pass

            log.info(
                "Misidentification: %s targeted real user #%s# (after 3-min delay).",
                interaction.user, id_clean,
            )

    # ── !anomaly — force spawn ───────────────────────────────────────

    @commands.command(name="anomaly")
    async def anomaly_cmd(self, ctx: commands.Context):
        """Force-spawn an anomaly immediately.  Boss only."""
        if not is_boss(ctx.author):
            await ctx.send("Access denied. Boss clearance required.", delete_after=10)
            return

        max_active = get_setting("anomaly_max")
        if len(self._active) >= max_active:
            await ctx.send(
                f"Maximum anomalies active ({max_active}). Wait for containment.",
                delete_after=10,
            )
            return

        anomaly = await self._spawn_anomaly()
        if anomaly:
            await ctx.send(
                f"Anomaly {anomaly.identity_name} deployed.",
                delete_after=10,
            )
        else:
            await ctx.send("Failed to deploy anomaly.", delete_after=10)


# ── Setup ────────────────────────────────────────────────────────────

async def setup(bot: commands.Bot):
    await bot.add_cog(AnomalyCog(bot))
