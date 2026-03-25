"""
EDU (Elementary Discourse Unit) data models.

Each EDU is a self-contained atomic fact or event extracted from a
conversation session between RPG characters, enriched with the turn
IDs from which it was derived.
"""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class EDU(BaseModel):
    """A single Elementary Discourse Unit extracted from a session."""

    edu_text: str = Field(
        ...,
        description=(
            "Content of the extracted EDU — self-contained and informative, "
            "expressed without pronouns or ambiguous references."
        ),
    )
    source_turn_ids: List[int] = Field(
        ...,
        description=(
            "List of turn IDs (integers) from which this EDU was extracted "
            "or referenced, e.g. [1], [3, 5]."
        ),
    )


class EDUExtractionResult(BaseModel):
    """Container for all EDUs extracted from one conversation session."""

    edus: List[EDU]
