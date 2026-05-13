"""
Role / permission helpers.
"""

import discord
import config


def has_role(member: discord.Member, role_id: int) -> bool:
    """Check whether *member* has a role with the given ID."""
    return any(r.id == role_id for r in member.roles)


# ── Convenience shortcuts ────────────────────────────────────────────

def is_owner(member: discord.Member) -> bool:
    return has_role(member, config.ROLE_OWNER)

def is_boss(member: discord.Member) -> bool:
    return has_role(member, config.ROLE_OWNER)

def is_builder(member: discord.Member) -> bool:
    return has_role(member, config.ROLE_BUILDER)

def is_tester(member: discord.Member) -> bool:
    return has_role(member, config.ROLE_TESTER)

def is_gatherer(member: discord.Member) -> bool:
    return has_role(member, config.ROLE_GATHERER)

def is_supervisor_builder(member: discord.Member) -> bool:
    return has_role(member, config.ROLE_SUPERVISOR_BUILDER)

def is_supervisor_tester(member: discord.Member) -> bool:
    return has_role(member, config.ROLE_SUPERVISOR_TESTER)

def is_supervisor_gatherer(member: discord.Member) -> bool:
    return has_role(member, config.ROLE_SUPERVISOR_GATHERER)
