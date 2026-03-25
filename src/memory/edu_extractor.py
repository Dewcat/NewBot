"""
EDU extractor: calls the OpenAI chat-completions API and parses the result.

Typical usage
-------------
    import os
    from memory import EDUExtractor

    extractor = EDUExtractor(api_key=os.environ["OPENAI_API_KEY"])
    result = extractor.extract(session_text, speaker_names=["珏", "露", "哥布林"])
    for edu in result.edus:
        print(edu.edu_text, "←", edu.source_turn_ids)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from .models import EDUExtractionResult
from .prompts import build_edu_extraction_messages

logger = logging.getLogger(__name__)

# Type alias that is compatible with the OpenAI SDK's expected message format.
_Message = Dict[str, Any]


class EDUExtractor:
    """Extract Elementary Discourse Units (EDUs) from a session text.

    Parameters
    ----------
    api_key:
        OpenAI API key.  If *None*, the ``openai`` library will look for the
        ``OPENAI_API_KEY`` environment variable automatically.
    model:
        OpenAI chat-completion model to use (default: ``"gpt-4o-mini"``).
    temperature:
        Sampling temperature passed to the API (default: ``0``).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
        temperature: float = 0.0,
    ) -> None:
        try:
            from openai import OpenAI  # lazy import — optional dependency
        except ImportError as exc:
            raise ImportError(
                "The 'openai' package is required by EDUExtractor. "
                "Install it with: pip install openai"
            ) from exc

        self._client = OpenAI(api_key=api_key)
        self._model = model
        self._temperature = temperature

    def extract(
        self,
        session_text: str,
        speaker_names: List[str],
    ) -> EDUExtractionResult:
        """Run EDU extraction on *session_text*.

        Parameters
        ----------
        session_text:
            The full battle or conversation session text with numbered turns.
        speaker_names:
            List of participant names appearing in the session.

        Returns
        -------
        EDUExtractionResult
            Parsed result containing all extracted EDUs.

        Raises
        ------
        ValueError
            If the API response cannot be parsed as a valid
            :class:`EDUExtractionResult`.
        """
        messages: List[_Message] = build_edu_extraction_messages(session_text, speaker_names)

        logger.debug(
            "Calling %s for EDU extraction (%d turns detected).",
            self._model,
            session_text.count("Turn "),
        )

        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=self._temperature,
            response_format={"type": "json_object"},
        )

        raw_content = response.choices[0].message.content or ""
        logger.debug("Raw EDU extraction response: %s", raw_content)

        try:
            data = json.loads(raw_content)
            result = EDUExtractionResult.model_validate(data)
        except Exception as exc:
            raise ValueError(
                f"Failed to parse EDU extraction response: {exc}\n"
                f"Raw response: {raw_content}"
            ) from exc

        logger.info("Extracted %d EDUs from session.", len(result.edus))
        return result
