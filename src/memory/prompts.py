"""
EDU extraction prompt templates.

The prompting strategy is modelled after the EMem approach
(https://github.com/KevinSRR/EMem): a system message defines what an EDU is
and lists concrete requirements, and a one-shot example (user + assistant turn)
guides the model before the real session is injected as a final user message.

Usage
-----
    from memory.prompts import build_edu_extraction_messages

    messages = build_edu_extraction_messages(session_text, speaker_names)
    # Pass `messages` to the OpenAI chat-completions API.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from .models import EDU, EDUExtractionResult

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

EDU_EXTRACTION_SYSTEM_PROMPT = (
    "Given a conversation session between speakers with numbered turns, "
    "your task is to decompose it into Elementary Discourse Units (EDUs) "
    "— short spans of text that are minimal yet complete in meaning. "
    "Each EDU should express a single fact, event, or proposition and be "
    "atomic (not easily divisible further while still making sense). "
    "It is important that you preserve all information from the conversation "
    "— no detail should be lost in the extraction process.\n"
    "\n"
    "Requirements for Conversation EDUs with Turn Attribution:\n"
    "1. Each EDU should be a self-contained unit of meaning that can be "
    "understood independently. It should not depend on any other EDU for "
    "understanding, although it may relate to it.\n"
    "2. Avoid pronouns or ambiguous references — use specific character names "
    "and details, and consistently use the most informative name for each "
    "entity in all EDUs.\n"
    "3. The extracted EDUs must include all information conveyed in the "
    "current session. The extracted EDUs should collectively capture "
    "everything discussed.\n"
    "4. For each EDU, you must provide the source_turn_ids field containing "
    "a list of turn ID integers from which the EDU was extracted or "
    "referenced (e.g. [1], [3, 5], etc.).\n"
    "5. EDUs can span multiple turns if they represent the same factual unit "
    "— in such cases, include all relevant turn IDs.\n"
    "6. Focus on extracting facts, events, and substantive information rather "
    "than conversational pleasantries.\n"
    "7. Infer and add complete temporal context where needed for clarity.\n"
    "8. Pay attention to capturing all details, facts, decisions, status "
    "effects, skill uses, damage dealt, and other substantive information "
    "from all speakers.\n"
    "9. Your final output must be a valid JSON string following this schema:\n"
    f"{EDUExtractionResult.model_json_schema()}"
)

# ---------------------------------------------------------------------------
# One-shot example
# ---------------------------------------------------------------------------

_ONE_SHOT_SESSION = """\
Round 1

Turn 1:
露 used 火球术 on 哥布林, dealing 12 magic damage. 哥布林 is now burning (intensity 2, 3 turns).

Turn 2:
哥布林 attacked 露, dealing 5 physical damage. 露 now has 45 HP.

Turn 3:
珏 used 铁壁 on herself, gaining guard (intensity 2, 5 turns).

Round 2

Turn 4:
露 used 群体治疗, restoring 8 HP to all allies. 珏 now has 58 HP. 笙 now has 62 HP.

Turn 5:
哥布林 is burning — suffered 2 damage at end of round. 哥布林 now has 18 HP."""

_ONE_SHOT_EDUS = [
    EDU(
        edu_text="露 used 火球术 on 哥布林 during Round 1, Turn 1, dealing 12 magic damage.",
        source_turn_ids=[1],
    ),
    EDU(
        edu_text="哥布林 received the burn status effect (intensity 2, lasting 3 turns) after being hit by 露's 火球术 in Round 1, Turn 1.",
        source_turn_ids=[1],
    ),
    EDU(
        edu_text="哥布林 attacked 露 in Round 1, Turn 2, dealing 5 physical damage.",
        source_turn_ids=[2],
    ),
    EDU(
        edu_text="露's HP dropped to 45 after being attacked by 哥布林 in Round 1, Turn 2.",
        source_turn_ids=[2],
    ),
    EDU(
        edu_text="珏 used 铁壁 on herself in Round 1, Turn 3, gaining the guard status effect (intensity 2, lasting 5 turns).",
        source_turn_ids=[3],
    ),
    EDU(
        edu_text="露 used 群体治疗 in Round 2, Turn 4, restoring 8 HP to all allies.",
        source_turn_ids=[4],
    ),
    EDU(
        edu_text="珏's HP rose to 58 after 露's 群体治疗 in Round 2, Turn 4.",
        source_turn_ids=[4],
    ),
    EDU(
        edu_text="笙's HP rose to 62 after 露's 群体治疗 in Round 2, Turn 4.",
        source_turn_ids=[4],
    ),
    EDU(
        edu_text="哥布林 suffered 2 burn damage at the end of Round 2, Turn 5, reducing its HP to 18.",
        source_turn_ids=[5],
    ),
]

_ONE_SHOT_OUTPUT = EDUExtractionResult(edus=_ONE_SHOT_EDUS).model_dump_json()

# Speaker names that appear in the one-shot battle session above.
_ONE_SHOT_SPEAKER_NAMES: List[str] = ["露", "珏", "笙", "哥布林"]

# ---------------------------------------------------------------------------
# Public helper
# ---------------------------------------------------------------------------


def build_edu_extraction_messages(
    session_text: str,
    speaker_names: List[str],
) -> List[Dict[str, Any]]:
    """Build the chat-completion message list for EDU extraction.

    Parameters
    ----------
    session_text:
        The full battle / conversation session text with numbered turns.
    speaker_names:
        List of participant names appearing in the session (e.g.
        ["珏", "露", "哥布林"]).

    Returns
    -------
    list[dict[str, Any]]
        A list of ``{"role": ..., "content": ...}`` dicts ready to be passed
        to the OpenAI chat-completions API.
    """
    one_shot_speaker_str = ", ".join(_ONE_SHOT_SPEAKER_NAMES)
    speaker_str = ", ".join(speaker_names)
    return [
        {"role": "system", "content": EDU_EXTRACTION_SYSTEM_PROMPT},
        # One-shot: user
        {
            "role": "user",
            "content": (
                f"Session conversation:\n{_ONE_SHOT_SESSION}"
                f"\n\nSpeaker names: {one_shot_speaker_str}"
            ),
        },
        # One-shot: assistant
        {"role": "assistant", "content": _ONE_SHOT_OUTPUT},
        # Real request
        {
            "role": "user",
            "content": (
                f"Session conversation:\n{session_text}"
                f"\n\nSpeaker names: {speaker_str}"
            ),
        },
    ]
