"""
Random code generation for the Builder system.
"""

import random
import string

import config

# Printable characters visible on both PC and mobile.
# Excludes whitespace / control chars that render inconsistently.
CHAR_POOL = string.ascii_letters + string.digits + "!@#$%*()-_=+[]{}|;:',.<>?/~`"


def generate_code() -> str:
    """
    Generate a 10-character code string.
    - 10 % chance the code is the trap code "&^^^&".
    - Otherwise a random string from CHAR_POOL, guaranteed NOT to contain "&^^^&".
    """
    if random.random() < config.TRAP_CHANCE:
        return config.TRAP_CODE

    while True:
        code = "".join(random.choices(CHAR_POOL, k=config.CODE_LENGTH))
        if config.TRAP_CODE not in code:
            return code


def mutate_code(code: str) -> str:
    """
    Return a copy of *code* where there is a 10 % chance that one random
    character (that is NOT part of the trap sequence "&^^^&") is replaced
    with a different random character.

    If no mutation happens the original code is returned unchanged.
    """
    if random.random() >= 0.10:
        return code          # no mutation

    # Build list of indices safe to mutate (not inside a "&^^^&" span)
    trap = config.TRAP_CODE
    protected: set[int] = set()
    start = 0
    while True:
        idx = code.find(trap, start)
        if idx == -1:
            break
        for i in range(idx, idx + len(trap)):
            protected.add(i)
        start = idx + 1

    safe_indices = [i for i in range(len(code)) if i not in protected]
    if not safe_indices:
        return code          # entire string is the trap – nothing to mutate

    target = random.choice(safe_indices)
    original_char = code[target]

    # Pick a different character
    new_char = original_char
    while new_char == original_char:
        new_char = random.choice(CHAR_POOL)

    return code[:target] + new_char + code[target + 1:]
