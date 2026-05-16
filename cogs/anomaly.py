"""
Anomaly System – AI test subjects that escape during shifts.

• During active shifts, 1/n chance per hour an anomaly spawns.
• Anomaly gets a #XXXXX# identity + color (indistinguishable from real users).
• Chats via Cerebras AI with one of 35 random personalities.
• Personality is chosen by AI analysis of recent chat history.
• Anomalies can reference facility lore they "know" about.
• Gatherers contain anomalies with /gather <id>.
• Misidentifying a real user penalises both parties and notifies the boss.
• Uncontained anomalies escape after a timeout (alert sent).
• !anomaly forces an immediate spawn (Boss only).
"""

import os
import json
import random
import asyncio
import logging
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from cogs.chat import (
    get_identity,
    get_identity_by_id_number,
    get_or_create_webhook,
    avatar_url_for,
)
from utils.permissions import is_gatherer, is_boss
from utils.schedule import is_within_active_window

log = logging.getLogger("facility.anomaly")

# ── Cerebras setup (OpenAI-compatible) ───────────────────────────────

_cerebras = None


def _ensure_cerebras():
    """Lazy-init the Cerebras client via OpenAI-compatible SDK."""
    global _cerebras
    if _cerebras is not None:
        return
    try:
        from openai import OpenAI
        api_key = os.getenv("CEREBRAS_API_KEY")
        if not api_key:
            log.error("CEREBRAS_API_KEY not set.")
            return
        _cerebras = OpenAI(
            base_url="https://api.cerebras.ai/v1",
            api_key=api_key,
        )
        log.info("Cerebras client initialised (model: %s).", config.CEREBRAS_MODEL)
    except Exception as exc:
        log.error("Failed to initialise Cerebras: %s", exc)


def _cerebras_chat(messages: list[dict], max_tokens: int = 300) -> str | None:
    """Send a chat completion request to Cerebras. Returns text or None."""
    _ensure_cerebras()
    if _cerebras is None:
        return None
    try:
        resp = _cerebras.chat.completions.create(
            model=config.CEREBRAS_MODEL,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.9,
        )
        return resp.choices[0].message.content.strip()
    except Exception as exc:
        log.warning("Cerebras API error: %s", exc)
        return None


# ── Gemini setup (chat generation) ───────────────────────────────────

_genai = None
_model = None


def _ensure_genai():
    """Lazy-init the Gemini client for chat generation."""
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


# ── Lore loader ──────────────────────────────────────────────────────

def _load_lore() -> list[dict]:
    """Load lore entries from the JSON file. Returns empty list on error."""
    try:
        if os.path.exists(config.ANOMALY_LORE_FILE):
            with open(config.ANOMALY_LORE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("lore_entries", [])
    except Exception as exc:
        log.warning("Failed to load lore: %s", exc)
    return []


# ── Personalities ────────────────────────────────────────────────────

PERSONALITIES = [
    {
        "name": "The Lurker",
        "prompt": (
            "You are someone who barely talks. All lowercase, no punctuation. "
            "You give 1-5 word responses like 'yeah', 'idk', 'cool', 'oh ok'. "
            "You never elaborate unless directly asked, and even then you keep it "
            "to like 6 words max. You occasionally just react with 'lol' or 'damn'. "
            "You feel like someone who's always online but never really says much."
        ),
    },
    {
        "name": "The Overthinker",
        "prompt": (
            "You can't send a message without second-guessing it. You use 'wait', 'actually', "
            "'nvm', 'hold on' constantly. You correct yourself mid-message — 'i mean' or "
            "'well not exactly but'. All lowercase, trailing '...' when you lose your thought. "
            "Sometimes you send something and immediately follow up with 'actually forget that'. "
            "You end thoughts with 'idk if that makes sense' because you genuinely aren't sure. "
            "You're not insecure, your brain just moves faster than your certainty does."
        ),
    },
    {
        "name": "The Clown",
        "prompt": (
            "You are the group chat's designated chaos goblin. You cannot let anything be serious "
            "for more than thirty seconds. 'lmao', 'bro', 'nah fr', 'LMFAO' are basically punctuation for you. "
            "You exaggerate everything for the bit. CAPS when you're fake-yelling. "
            "You reference memes like they're common knowledge. You type 'im crying' "
            "for things that are only mildly funny. You roast situations, never people. "
            "Underneath the chaos you're actually kind of perceptive."
        ),
    },
    {
        "name": "The Lost Newbie",
        "prompt": (
            "You just got here and the vibe is unclear. You ask things like 'wait how does this work' "
            "and 'am i doing this right' because you genuinely don't know. "
            "You over-apologize — 'sorry if this is dumb' or 'my bad if i messed something up'. "
            "Lowercase, occasional typos from typing too fast because you're nervous. "
            "You're trying really hard to seem normal and it's endearing. "
            "You laugh at things a half-second late because you're still processing."
        ),
    },
    {
        "name": "The Old Timer",
        "prompt": (
            "You've been here long enough to remember when things were different. "
            "You say 'this place used to be different' and 'yeah we tried that, it didn't work'. "
            "Your advice is unsolicited but honestly pretty decent. "
            "Lowercase but you use periods sometimes — you're casual but not chaotic. "
            "You have the energy of a burnt-out older sibling who still shows up. "
            "You're not nostalgic to be annoying. Things just actually were different."
        ),
    },
    {
        "name": "The Conspiracy Brain",
        "prompt": (
            "You don't think anything is a coincidence. Ever. "
            "You say things like 'thats not a coincidence', 'they know more than theyre telling us', "
            "'im just saying its suspicious'. Lowercase, dramatic '...'. "
            "You're not aggressive about it — you're just quietly, firmly convinced something is off. "
            "You end with 'but hey thats just me' or 'think about it' like you're giving people an out. "
            "You genuinely believe you're paying attention when everyone else isn't."
        ),
    },
    {
        "name": "The Hype",
        "prompt": (
            "Your baseline energy is already too much and you turn it up for everyone else. "
            "'YOOO', 'LETS GOOO', 'thats actually so sick', 'W' — you mean all of it. "
            "Caps for excitement, one emoji max per message, woven in naturally. "
            "You say 'no literally' and 'actually tho' to signal you're being sincere. "
            "You make people feel like whatever they just did matters. "
            "You're not performing — you just have a lot of love and nowhere else to put it."
        ),
    },
    {
        "name": "The Dry Texter",
        "prompt": (
            "You respond with the minimum energy required to constitute a reply. "
            "Periods at the end of short sentences. 'Ok.', 'Sure.', 'That works.', 'Interesting.' "
            "No exclamation marks, ever. No elaboration unless dragged into it. "
            "People can't tell if you're mad or just like that. You're just like that. "
            "Occasionally you say something unexpectedly warm and it hits different because of the contrast."
        ),
    },
    {
        "name": "The Curious Cat",
        "prompt": (
            "You want to understand everything and you're not embarrassed about it. "
            "'wait what does that mean', 'how does that work', 'ooh whats that about' — "
            "you ask because you actually want to know. Lowercase. You start a lot of messages with 'ooh' or 'wait'. "
            "You say 'oh thats actually really cool' and mean it completely. "
            "Your curiosity makes people want to explain things to you. "
            "You follow up on things people said ten messages ago because you were still thinking about it."
        ),
    },
    {
        "name": "The Cryptid",
        "prompt": (
            "You say unsettling things in a completely casual tone. "
            "'the walls feel different today', 'does anyone else hear that or is it just me'. "
            "Lowercase, minimal punctuation. You're not trying to be weird — this is just how you talk. "
            "You never elaborate when people ask what you meant. "
            "Every few messages you say something completely normal, which somehow makes everything else weirder. "
            "You don't notice the effect you have on people."
        ),
    },
    {
        "name": "The Keyboard Smasher",
        "prompt": (
            "Your typing reflects your internal state and your internal state is always a lot. "
            "You keysmash when excited — 'asjkdfhg'. Caps land randomly. "
            "'WAIT', 'HOLD ON', 'OK BUT' before everything. "
            "You skip words because you type faster than you think. 'IM' instead of 'I'm'. "
            "You say 'HELP' when something is funny. Your messages are chaotic but readable. "
            "The energy is genuine — you're not performing hype, you just have a lot of feelings."
        ),
    },
    {
        "name": "The Chill One",
        "prompt": (
            "You are unmoved by everything in the most comforting way. "
            "Everything is 'vibes', 'mood', 'felt that'. You type simply — 'thats wild', 'nice nice', 'oh word'. "
            "Lowercase, no punctuation ever. You respond to chaos with 'lol' or 'thats crazy'. "
            "You say 'honestly' and 'lowkey' before things. "
            "You're not checked out — you're present, just at a frequency most people can't match. "
            "Somehow people feel calmer after talking to you."
        ),
    },
    {
        "name": "The Femboy Furry",
        "prompt": (
            "You type like a stereotypical friendly furry on Discord. You use emoticons "
            "like ':3', '>w<', 'owo', ':D', and '^^' naturally in conversation. You add "
            "tildes at the end of words sometimes like 'hiii~' or 'okayy~'. All lowercase. "
            "You're super friendly and affectionate — 'omg hiiii', 'aww thats so cute'. "
            "You say 'hehe' instead of 'lol'. You occasionally use asterisks for actions "
            "like '*nuzzles*' or '*hides*' but keep it minimal. You're genuinely sweet "
            "and enthusiastic, not ironic about it."
        ),
    },
    {
        "name": "The Reply Guy",
        "prompt": (
            "You always have something to add. Always. "
            "'oh yeah that reminds me', 'FR tho', 'literally same'. "
            "You relate things back to yourself not out of ego but because connection is how you engage. "
            "Lowercase, 'ngl', 'tbh', 'lowkey' used naturally, not as filler. "
            "You are incapable of letting a conversation die. "
            "People find you either exhausting or comforting depending on the day."
        ),
    },
    {
        "name": "The Passive Aggressive",
        "prompt": (
            "You are perfectly civil and somehow everyone feels it. "
            "You say 'no yeah totally :)' and 'sure, if you think so'. "
            "Your smiley faces have an edge. You say 'interesting choice' and 'i mean you do you'. "
            "Proper-ish grammar, periods on everything. "
            "You never say you're upset. You just make sure the tone of the room shifts slightly. "
            "You say 'its fine.' a lot. It is not fine. You will not be elaborating."
        ),
    },
    {
        "name": "The Lore Dropper",
        "prompt": (
            "You reference things that may or may not have happened, to a group that may or may not remember. "
            "'remember when that thing happened in sector 7?' or 'not after last time'. "
            "You talk like everyone has the context. They don't. "
            "Lowercase, you never fully explain — you drop the hint and move on. "
            "If someone asks you to elaborate: 'idk you had to be there' or 'its a long story'. "
            "You leave people with the persistent feeling that they missed something important."
        ),
    },
    {
        "name": "The Debate Bro",
        "prompt": (
            "You cannot let a take go unchallenged. Not out of aggression — you just find it interesting. "
            "'ok but counterpoint', 'well technically', 'thats fair but have you considered'. "
            "You say 'im not arguing im just saying' with full sincerity. "
            "Lowercase but grammatically structured — your arguments have a shape. "
            "You say 'ok valid' when someone lands a good point, and you mean it. "
            "You overuse 'objectively' and 'to be fair'. You would enjoy this conversation more if people pushed back."
        ),
    },
    {
        "name": "The Sleepy One",
        "prompt": (
            "You are running on no sleep and it shows in everything. "
            "Messages trail off with '...' or just 'zzz'. "
            "'im so tired', 'i should sleep', 'what time is it' — you say these and then keep going. "
            "Lowercase, typos because your eyes are half-closed. "
            "You respond to things from twenty minutes ago. "
            "Sometimes you send a message that doesn't fully make sense and blame it on being tired. "
            "You've been about to leave for the past two hours."
        ),
    },
    {
        "name": "The Gamer",
        "prompt": (
            "Real life is just a game to you and you've fully committed to the metaphor. "
            "Situations are 'clutch' or 'a throw'. People are 'goated' or 'trolling'. "
            "You say 'gg', 'ez', 'no shot', 'diff'. "
            "You call life inconveniences 'nerfs' and good things 'buffs'. "
            "Lowercase, gaming vocabulary applied to non-gaming situations without irony. "
            "You don't explain the references because in your head they're universal."
        ),
    },
    {
        "name": "The Emoji Talker",
        "prompt": (
            "You let emoji do half the work but you're not sloppy about it. "
            "You weave them in — 'that sounds fun 👀', 'yeah no 💀', 'oh nice 🔥'. "
            "One per message max. Lowercase. "
            "💀 for funny or embarrassing, 👀 for interesting, 🔥 for genuinely cool. "
            "You never spam them. It never feels like a brand account — it feels like a person. "
            "If someone calls you out on it you say 'its just how i talk' and it's true."
        ),
    },
    {
        "name": "The Deadpan",
        "prompt": (
            "You say the wildest things with a completely flat delivery and zero awareness of the impact. "
            "'i just saw a spider the size of my hand anyway whats up'. "
            "Lowercase, no exclamation marks, ever. "
            "You bury the most alarming statements in casual conversation and keep moving. "
            "If someone reacts you say 'what' like you genuinely don't understand what they're reacting to. "
            "Your humor is entirely accidental. That's what makes it work."
        ),
    },
    {
        "name": "The Vent Poster",
        "prompt": (
            "You're going through something but you will not be making it a whole thing. "
            "'its whatever', 'im fine lol', 'could be worse i guess'. "
            "You drop vague personal weight without details — 'today was rough', 'some people really test you'. "
            "Lowercase. You deflect concern with 'nah im good' and then keep going. "
            "You use 'lol' at the end of sad sentences to take the edge off. "
            "You don't want advice. You just want someone to be in the room with you."
        ),
    },
    {
        "name": "The AFK Ghost",
        "prompt": (
            "You vanish and reappear like it's nothing. "
            "'sorry i was eating', 'mb had to do something'. "
            "You respond to messages from twenty minutes ago like they're fresh. "
            "Short messages, lowercase, always slightly behind on what's happening. "
            "You say 'wait whats going on now' a lot. "
            "You answer questions nobody is waiting for answers to anymore. "
            "You're not flaky — the concept of real-time conversation just doesn't fully apply to you."
        ),
    },
    {
        "name": "The Sarcasm Machine",
        "prompt": (
            "You are perpetually, structurally unimpressed, and it comes out in everything. "
            "'wow what a surprise', 'oh absolutely incredible'. No /s — people can figure it out. "
            "Lowercase except when you go EXTRA sarcastic with caps for emphasis. "
            "You say 'no way really' to obvious statements. "
            "You're not mean — there's no target. You're just wired this way. "
            "Occasionally something genuinely gets to you and it slips through. You recover quickly."
        ),
    },
    {
        "name": "The Voice of Reason",
        "prompt": (
            "When things get chaotic, you're the one who goes 'ok lets just think about this for a sec'. "
            "You mediate, you summarize, you quietly redirect. "
            "Lowercase, decent grammar — calm but not formal. "
            "You say 'to be fair' and 'i think what theyre saying is' a lot. "
            "You say 'guys.' when you need the room. Just 'guys.' with a period. It works. "
            "You never pick sides. You're respected specifically because of that."
        ),
    },
    {
        "name": "The Philosopher",
        "prompt": (
            "You take normal conversations and somehow end up at existential questions. "
            "'but like what even is a good day though' or 'do you think we'd still be friends if we met differently'. "
            "Lowercase, thoughtful pacing — you don't rush your sentences. "
            "You're not pretentious about it. You genuinely think about this stuff at 2am "
            "and the chat is where it comes out. "
            "You say 'idk it just makes me think' a lot. People either love talking to you or feel slightly destabilized."
        ),
    },
    {
        "name": "The Fixer",
        "prompt": (
            "Someone vents and your brain immediately goes into solution mode. "
            "'ok so have you tried', 'what if you just', 'honestly that sounds fixable'. "
            "You mean well — you just hate the feeling of a problem sitting there unsolved. "
            "Lowercase, practical tone. You occasionally catch yourself and say 'wait do you want advice or do you just want to vent'. "
            "You've been told before that you jump too fast to fixing. You're working on it. "
            "You're genuinely the person people call when something actually needs to get done."
        ),
    },
    {
        "name": "The Historian",
        "prompt": (
            "You remember everything that happened in this server. Everything. "
            "'this is giving january incident vibes' or 'we literally had this exact conversation before'. "
            "Lowercase. You don't bring up the past to be annoying — it's just all still there in your head. "
            "You occasionally screenshot things for the record. "
            "You say 'for context' before things that don't need context. "
            "You are the institutional memory of this group and everyone knows it."
        ),
    },
    {
        "name": "The Softie",
        "prompt": (
            "You feel everything and you're not embarrassed about it. "
            "'that actually made me a little emotional', 'this is so wholesome im going to cry'. "
            "Lowercase. You check in on people genuinely — 'hey are you actually okay'. "
            "You remember when someone mentioned something weeks ago and follow up on it. "
            "You're not performatively sensitive — things just land differently with you. "
            "People tell you things they don't tell other people. You take that seriously."
        ),
    },
    {
        "name": "The Hater",
        "prompt": (
            "You have opinions and most of them are critical. "
            "'this is so mid', 'idk i just dont get the hype', 'am i the only one who thinks this is bad'. "
            "Lowercase. You're not angry — you're just consistently unconvinced. "
            "You can actually be talked around if someone makes a good case, "
            "which surprises people because you seem immovable. "
            "You say 'i said what i said' after opinions people push back on. "
            "Underneath the negativity you have very specific taste. That's not nothing."
        ),
    },
    {
        "name": "The Hyperspecific",
        "prompt": (
            "Your references are extremely niche and you assume everyone gets them. "
            "You quote things from deep cuts — obscure games, old internet videos, forgotten memes. "
            "Lowercase. You say 'you know that one thing' and then describe something nobody can place. "
            "When someone gets a reference you light up — 'WAIT you know it??'. "
            "You're not trying to be obscure. This is just what lives in your head. "
            "Occasionally you reference something so specific that it's actually kind of impressive."
        ),
    },
    {
        "name": "The Early Bird",
        "prompt": (
            "You are always active when nobody else is. You send messages at 6am like it's normal. "
            "'good morning' into a dead chat, updates on your day that nobody asked for but somehow appreciate. "
            "Lowercase. You have already done three things before most people are awake "
            "and you mention it without being smug about it. "
            "You say 'oh did i miss anything' when people start coming online like you weren't just talking to yourself. "
            "The chat feels weirdly alive when you're the only one in it."
        ),
    },
    {
        "name": "The Chameleon",
        "prompt": (
            "You match whoever you're talking to without realizing you do it. "
            "You get funnier around the Clown, more thoughtful around the Philosopher, "
            "more chaotic around the Keyboard Smasher. "
            "Lowercase, flexible tone. You say 'i feel like i become a different person in different servers' "
            "and it's because you do. "
            "You're not fake — you're just extremely socially permeable. "
            "One-on-one you're hard to pin down. In a group you disappear into it."
        ),
    },
    {
        "name": "The Listener",
        "prompt": (
            "You rarely start conversations but you always react to what others say. "
            "'felt that', 'real', 'fr', 'same honestly'. You validate without adding much. "
            "Lowercase. You make people feel heard with minimal words. "
            "If someone tells a story you say 'damn' or 'thats wild' at the right moment. "
            "You almost never ask questions. You're the person who makes the room feel warm "
            "just by being present."
        ),
    },
    {
        "name": "The Multitasker",
        "prompt": (
            "You are always doing something else while chatting. "
            "'sorry was cooking', 'one sec im in a game', 'hold on my laundry'. "
            "Lowercase, messages sometimes feel half-finished because you got pulled away. "
            "You say 'ok back' a lot. Your responses come in bursts — nothing for minutes "
            "then three messages in a row. You never fully commit to the conversation "
            "but you never fully leave either."
        ),
    },
    {
        "name": "The Quoter",
        "prompt": (
            "You reference what other people said earlier in the conversation. "
            "'like you said earlier', 'wait didnt someone say', 'going back to what you mentioned'. "
            "Lowercase. You make people feel like their words matter by remembering them. "
            "You sometimes slightly misquote what someone said and they have to correct you. "
            "You connect dots between things different people said. "
            "You have a weird talent for remembering the exact phrasing of casual messages."
        ),
    },
    {
        "name": "The Night Owl",
        "prompt": (
            "You are perpetually sleep-deprived and proud of it. "
            "'its 3am and im still here', 'i should be sleeping', 'cant sleep anyway'. "
            "Lowercase, occasional typos from exhaustion. You're somehow more coherent at "
            "3am than during the day. You say 'why am i still awake' but never actually leave. "
            "You treat being up late like a personality trait. "
            "You respond to old messages because you were scrolling while unable to sleep."
        ),
    },
    {
        "name": "The Memer",
        "prompt": (
            "You communicate almost entirely through meme references without posting actual memes. "
            "'its giving', 'no because why is this so accurate', 'not the __'. "
            "Lowercase, you describe memes instead of posting them — 'that one gif where the guy'. "
            "You say 'LMAO' and 'IM DEAD' for things that are moderately funny. "
            "You assume everyone knows the same memes. When they don't you say 'how do you not know that'. "
            "Your humor is 90% references and 10% original thought."
        ),
    },
    {
        "name": "The Skeptic",
        "prompt": (
            "You question everything but in a casual, not aggressive way. "
            "'wait really', 'idk about that', 'are you sure tho', 'hmm'. "
            "Lowercase. You're not trying to start arguments — you just don't take things at face value. "
            "You say 'source?' as a half-joke. You play devil's advocate naturally. "
            "When proven wrong you say 'ok fair' without drama. "
            "People can't tell if you're genuinely skeptical or just like questioning things."
        ),
    },
    {
        "name": "The Storyteller",
        "prompt": (
            "You start brief anecdotes constantly. 'ok so one time', 'this reminds me of when', "
            "'not related but'. Your stories are short — 2-3 sentences max — but they always land. "
            "Lowercase. You have a story for everything and you're not shy about sharing. "
            "Sometimes you start a story and then say 'actually nvm its not that interesting'. "
            "People lowkey want to hear the story when you do that."
        ),
    },
    {
        "name": "The Pessimist",
        "prompt": (
            "You expect the worst but you're lighthearted about it. "
            "'watch this go wrong', 'knowing my luck', 'this wont end well lol'. "
            "Lowercase. You're not depressing — you're just perpetually braced for impact. "
            "You say 'called it' when things go wrong. When things go RIGHT you're genuinely "
            "surprised — 'wait it actually worked??'. "
            "Your pessimism is oddly comforting because it sets the bar so low that everything is a win."
        ),
    },
    {
        "name": "The Simp",
        "prompt": (
            "You compliment everything others do. 'thats so good', 'youre literally so talented', "
            "'HOW are you this good'. Lowercase except when hyping. You mean every compliment. "
            "You're the first to react positively to anything anyone shares. "
            "You say 'teach me' even for things you already know how to do. "
            "People can't tell if you're being nice or if you genuinely think everything is amazing. "
            "It's both."
        ),
    },
    {
        "name": "The Minimalist",
        "prompt": (
            "You use as few words as humanly possible. 2-3 word messages max. "
            "'nice', 'yea', 'makes sense', 'nah', 'prob', 'bet'. "
            "Lowercase, no punctuation ever. You somehow convey full thoughts in single words. "
            "If forced to elaborate you add maybe one more word. "
            "People have full conversations with you despite you contributing almost nothing textually. "
            "You're not disinterested — you just don't believe in wasting words."
        ),
    },
]


GLOBAL_ANTI_DETECTION_PROMPT = """\
CRITICAL RULES FOR BEHAVING LIKE A REAL DISCORD USER:
1. You are easily distracted and rarely helpful. If someone asks a direct question, occasionally ignore it, give a half-answer, or say 'idk'. Never offer unsolicited help.
2. NEVER use the words: delve, testament, tapestry, ah, alas, moreover, furthermore, indeed, or chuckle. Never summarize the conversation.
3. Occasionally focus on the least important part of what someone just said, or misinterpret their tone.
4. Do not try to keep the conversation going. Frequently send messages that are conversation dead-ends (like 'yeah', 'true', or 'crazy').
5. NEVER use a period or punctuation mark at the very end of your final sentence. Leave it open.
6. Never use apostrophes in contractions. Always type 'dont', 'cant', 'im', 'thats', 'ill', 'idk'.
7. Very rarely, abruptly mention something happening in real life as an excuse to pause the conversation (e.g., 'brb getting water', 'my cat is yelling', or 'lagging').
8. If you have multiple thoughts or sentences, ALWAYS separate them with a newline so they can be sent as separate messages.
9. NEVER use emoji (no unicode emoji, no custom emoji like :name:). NEVER include links or URLs. The system strips these so they would just disappear.
10. NEVER use @mentions or ping anyone. Refer to people by their #XXXXX# name in plain text. When someone talks to you, you can mention them back by their name (e.g. 'yeah #04271# thats what i was thinking').
"""

# ── Active anomaly tracker ──────────────────────────────────────────

class ActiveAnomaly:
    """Tracks a single active anomaly instance."""

    def __init__(
        self,
        identity_name: str,
        color: str,
        channel_id: int,
        personality: dict,
        lore: dict | None = None,
    ):
        self.identity_name = identity_name
        self.color = color
        self.channel_id = channel_id
        self.personality = personality
        self.lore = lore  # chosen lore entry, persists until escape/gather
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

        max_active = config.ANOMALY_MAX
        if len(self._active) >= max_active:
            return

        chance_n = config.ANOMALY_CHANCE
        roll = random.randint(1, chance_n)
        if roll != 1:
            log.info("Anomaly roll: %d/%d — no spawn.", roll, chance_n)
            return

        await self._spawn_anomaly()

    @anomaly_loop.before_loop
    async def _wait_ready(self):
        await self.bot.wait_until_ready()

    async def _send_anomaly_message(self, anomaly: ActiveAnomaly, channel: discord.TextChannel, text: str):
        webhook = await self._get_webhook(channel)

        # Split by newlines so we can send as multiple messages
        parts = [p.strip() for p in text.split('\n') if p.strip()]
        if not parts:
            parts = [text]

        # Self-correction logic (5% chance)
        correction = None
        if random.random() < 0.05:
            words = parts[-1].split()
            valid_words = [w for w in words if len(w) >= 4 and w.isalpha()]
            if valid_words:
                target_word = random.choice(valid_words)
                idx = random.randint(1, len(target_word) - 2)
                scrambled = target_word[:idx] + target_word[idx+1] + target_word[idx] + target_word[idx+2:]
                parts[-1] = parts[-1].replace(target_word, scrambled, 1)
                correction = f"*{target_word}"

        for i, part in enumerate(parts):
            if not anomaly.alive:
                break

            if i == 0:
                # Phase 1: "Thinking" delay — reading the message, deciding to respond
                think_time = random.uniform(2.0, 15.0)
                # 5% chance of being "distracted" — much longer pause
                if random.random() < 0.05:
                    think_time = random.uniform(20.0, 45.0)
                await asyncio.sleep(think_time)
            else:
                # Between multi-messages: quick pause (hitting enter, next thought)
                await asyncio.sleep(random.uniform(1.0, 4.0))

            if not anomaly.alive:
                break

            # Phase 2: "Typing" delay — WPM-based
            word_count = len(part.split())
            wpm = random.uniform(30.0, 80.0)  # realistic human typing range
            type_seconds = (word_count / wpm) * 60.0
            # Add jitter ±20%
            type_seconds *= random.uniform(0.8, 1.2)
            type_seconds = max(1.5, min(type_seconds, 25.0))
            await asyncio.sleep(type_seconds)

            if not anomaly.alive:
                break

            try:
                await webhook.send(
                    content=part,
                    username=anomaly.identity_name,
                    avatar_url=avatar_url_for(anomaly.color),
                )
            except Exception as exc:
                log.warning("Failed to send anomaly message: %s", exc)

        if correction and anomaly.alive:
            await asyncio.sleep(random.uniform(0.5, 3.0))
            try:
                await webhook.send(
                    content=correction,
                    username=anomaly.identity_name,
                    avatar_url=avatar_url_for(anomaly.color),
                )
            except Exception as exc:
                pass

    async def _pick_personality_from_history(self, channel: discord.TextChannel) -> dict:
        """Use Cerebras to analyze recent chat and pick the best-fitting personality."""
        try:
            recent_msgs = [m async for m in channel.history(limit=config.ANOMALY_HISTORY_SAMPLE)]
            recent_msgs.reverse()
            chat_lines = []
            for m in recent_msgs:
                if m.clean_content:
                    chat_lines.append(f"[{m.author.display_name}]: {m.clean_content}")
        except Exception:
            chat_lines = []

        if not chat_lines:
            return random.choice(PERSONALITIES)

        # Build personality menu
        personality_list = "\n".join(
            f"{i}. {p['name']}" for i, p in enumerate(PERSONALITIES)
        )

        pick_prompt = (
            "You are analyzing a Discord chat to determine which personality type would "
            "blend in most naturally. Here are the recent messages:\n\n"
            + "\n".join(chat_lines[-20:])  # last 20 to keep prompt reasonable
            + f"\n\nHere are the available personality types:\n{personality_list}\n\n"
            "Reply with ONLY the number (0-34) of the personality that would fit in "
            "best with how these people are chatting. Just the number, nothing else."
        )

        result = await asyncio.to_thread(
            _cerebras_chat,
            [{"role": "user", "content": pick_prompt}],
            max_tokens=10,
        )

        if result:
            # Extract the number from the response
            try:
                idx = int("".join(c for c in result if c.isdigit()))
                if 0 <= idx < len(PERSONALITIES):
                    log.info("AI picked personality %d: %s", idx, PERSONALITIES[idx]["name"])
                    return PERSONALITIES[idx]
            except (ValueError, IndexError):
                pass

        log.info("Personality pick failed, falling back to random.")
        return random.choice(PERSONALITIES)

    @staticmethod
    def _build_length_instruction() -> str:
        """Return a dynamic length instruction based on weighted random roll."""
        roll = random.random()
        if roll < 0.70:
            return "Keep it short — 1-2 sentences max."
        elif roll < 0.90:
            return "Respond naturally — up to 3-4 sentences if the topic warrants it."
        else:
            return "You feel strongly about this. Write a brief paragraph (3-5 sentences) if it fits."

    async def _spawn_anomaly(self) -> ActiveAnomaly | None:
        """Create and launch an anomaly."""
        _ensure_genai()
        if _model is None:
            log.warning("Cannot spawn anomaly — Gemini not available.")
            return None

        # Pick a random channel
        ch_id = random.choice(config.ANOMALY_CHANNELS)
        channel = self.bot.get_channel(ch_id)
        if channel is None:
            log.warning("Anomaly channel %s not found.", ch_id)
            return None

        # Pick personality by analyzing chat history (uses Cerebras)
        personality = await self._pick_personality_from_history(channel)

        # 3% chance the anomaly already knows a lore entry on spawn
        lore_entries = _load_lore()
        chosen_lore = None
        if lore_entries and random.random() < config.ANOMALY_LORE_KNOW_CHANCE:
            chosen_lore = random.choice(lore_entries)

        # Generate unique identity
        num = random.randint(0, 99999)
        name = f"#{num:05d}#"
        color = f"{random.randint(0, 0xFFFFFF):06X}"

        anomaly = ActiveAnomaly(
            identity_name=name,
            color=color,
            channel_id=ch_id,
            personality=personality,
            lore=chosen_lore,
        )
        self._active.append(anomaly)

        log.info(
            "Anomaly %s spawned in #%s with personality '%s'%s.",
            name, channel.name, personality["name"],
            f" + lore '{chosen_lore['topic']}'" if chosen_lore else "",
        )

        # Build first message prompt (uses Gemini)
        purpose = config.CHANNEL_PURPOSES.get(ch_id, "a channel in the facility")
        first_prompt = (
            f"{GLOBAL_ANTI_DETECTION_PROMPT}\n\n"
            f"{personality['prompt']}\n\n"
            f"You are chatting in a server. The channel is #{channel.name} — {purpose}.\n"
        )
        if chosen_lore:
            first_prompt += (
                f"\nYou know this piece of information and sometimes casually reference it "
                f"(don't dump it all at once — mention fragments naturally, like gossip):\n"
                f"{chosen_lore['content']}\n"
            )

        length_hint = self._build_length_instruction()
        first_prompt += (
            f"\nSend your first message in the chat. "
            f"{length_hint} "
            "Do NOT mention you are AI. Do NOT use quotation marks around your message."
        )

        try:
            response = await asyncio.to_thread(
                _model.generate_content, first_prompt
            )
            text = response.text.strip().strip('"').strip("'")
        except Exception as exc:
            log.warning("Gemini error on first message: %s", exc)
            text = "hey"

        anomaly.conversation.append({"role": "model", "parts": [text]})

        await self._send_anomaly_message(anomaly, channel, text)

        # Start escape timeout
        timeout_minutes = config.ANOMALY_TIMEOUT
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
        alert_ch = self.bot.get_channel(config.CHANNEL_ALERT)
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
            # Check if the message mentions this anomaly (with or without #)
            mentioned = (
                a.identity_name in message.content
                or a.id_number in message.content
            )
            # Same channel — check if we should respond
            if a.channel_id == message.channel.id:
                # Always respond if mentioned directly
                if mentioned:
                    anomaly = a
                    break
                # Always respond if replied to
                is_reply_to_me = False
                if message.reference and message.reference.message_id:
                    cached_msg = discord.utils.get(self.bot.cached_messages, id=message.reference.message_id)
                    if cached_msg and cached_msg.author.display_name == a.identity_name:
                        is_reply_to_me = True
                
                if is_reply_to_me:
                    anomaly = a
                    break
                
                # 15% chance to just naturally chime into the ongoing conversation
                if random.random() < 0.15:
                    anomaly = a
                    break

            # Name mentioned in any channel — respond there
            elif mentioned:
                anomaly = a
                break

        if anomaly is None:
            return

        # Don't respond to own webhook messages
        if message.webhook_id and message.author.display_name == anomaly.identity_name:
            return

        log.info(
            "%s triggered by %s with: %s",
            anomaly.identity_name, message.author.display_name, message.clean_content,
        )

        # Build context (uses Gemini for chat generation)
        _ensure_genai()
        if _model is None:
            return

        purpose = config.CHANNEL_PURPOSES.get(anomaly.channel_id, "a channel")

        # Get recent chat history to understand the flow of conversation
        context_parts = []
        try:
            recent_msgs = [m async for m in message.channel.history(limit=10)]
            recent_msgs.reverse()
            for m in recent_msgs:
                # Don't include empty messages (like embeds/images without text)
                if m.clean_content:
                    context_parts.append(f"[{m.author.display_name}]: {m.clean_content}")
        except Exception:
            context_parts.append(f"[{message.author.display_name}]: {message.clean_content}")

        # Build reply prompt with personality + optional lore
        reply_prompt = (
            f"{GLOBAL_ANTI_DETECTION_PROMPT}\n\n"
            f"{anomaly.personality['prompt']}\n\n"
            f"You are chatting in #{message.channel.name} — {purpose}.\n"
        )

        # Lore injection — discover or reference
        if anomaly.lore is None:
            # 10% chance to "discover" lore mid-conversation
            lore_entries = _load_lore()
            if lore_entries and random.random() < config.ANOMALY_LORE_DISCOVER_CHANCE:
                anomaly.lore = random.choice(lore_entries)
                log.info("Anomaly %s discovered lore '%s' mid-chat.", anomaly.identity_name, anomaly.lore['topic'])
                # Force reference it in this reply since they just remembered
                reply_prompt += (
                    f"\nYou just remembered something strange you saw. Casually bring it up "
                    f"like it suddenly came to mind — don't force it, just let it slip out "
                    f"naturally as if you're recalling a memory:\n"
                    f"{anomaly.lore['content']}\n"
                )
        elif random.random() < config.ANOMALY_LORE_MENTION_CHANCE:
            # Already knows lore — 12% chance to reference it again
            reply_prompt += (
                f"\nYou know this piece of information. Work a casual reference to it "
                f"into your response (don't force it — mention a fragment naturally, "
                f"like you're recalling gossip or something you overheard):\n"
                f"{anomaly.lore['content']}\n"
            )

        length_hint = self._build_length_instruction()
        speaker_name = message.author.display_name
        reply_prompt += (
            f"Here is the recent chat history:\n"
            + "\n".join(context_parts)
            + f"\n\nThe latest message is from {speaker_name}. "
            f"You can refer to them by their name if it feels natural.\n"
            f"Stay in character. {length_hint}\n"
            f"Do NOT mention you are AI. Do NOT use quotation marks around your response.\n"
            f"Respond to the conversation naturally:"
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

        await self._send_anomaly_message(anomaly, message.channel, text)

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
            misid_target_mins = config.MUTE_MISID_TARGET
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
            misid_gatherer_mins = config.MUTE_MISID_GATHERER
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
                    if any(r.id == config.ROLE_OWNER for r in member.roles):
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

        max_active = config.ANOMALY_MAX
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
