"""Tests for the claim-without-tool-call detector.

When the assistant's prose claims an action ("I have saved the file") but no
tool was called in the same turn, the TUI should warn the user — the model
hallucinated the action. This file tests the regex that catches such claims.
"""
from __future__ import annotations

import pytest

from purr.app import _detect_uncalled_claim, _CLAIM_PATTERNS


@pytest.mark.parametrize("text", [
    # first-person past tense
    "I have saved the file to your desktop.",
    "I've saved it.",
    "I saved the file.",
    "I wrote the story to ~/Desktop/tail.md.",
    "I have written the brief to disk.",
    "I created a folder for you.",
    "I have created the event.",
    "I downloaded the file.",
    "I have downloaded the installer.",
    "I installed brew for you.",
    "I killed the process.",
    "I have killed pid 37593.",
    "I moved the file to Trash.",
    "I sent the email.",
    "I have sent the reminder.",
    "I added a note.",
    "I have added the event to your calendar.",
    "I cleaned up your Desktop.",
    "I launched the app.",
    "I opened the URL in your browser.",
    # first-person with adverbs
    "I just installed the package.",
    "I have just downloaded the file.",
    # future / commitment
    "I will save it for you.",
    "I will install brew.",
    "I'll create the folder.",
    # "Done —" / "Done:" style
    "Done — wrote 235 bytes to your file.",
    "Done — installed the package.",
    "Done: created folder ~/projects/foo",
    "Done - killed pid 37593",
])
def test_detects_action_claims(text: str) -> None:
    """Every 'I did X' / 'Done — X' style claim must be caught."""
    assert _detect_uncalled_claim(text) is not None, f"missed claim: {text!r}"


@pytest.mark.parametrize("text", [
    # conversational
    "Hi, how can I help you today?",
    "Here's the story you asked for:\n\nPixel the cat...",
    "Let me check what's running on your machine.",
    "Searching the web for that now.",
    "I can help you with that. What kind of story would you like?",
    "Here's the response from the API.",
    "I need to know more about the topic.",
    "I think we should try a different approach.",
    "Let me know if that works.",
    "Sure, I can do that — would you like it on your Desktop?",
    "Python is a programming language.",
    "",
    "The file you mentioned earlier was 200 bytes.",
    "I have a question for you.",
    "I have considered the alternative and rejected it.",  # Dross catchphrase
    # third-person narrative (e.g. inside a story) — must NOT trigger
    "The cat opened the box and found a treasure.",
    "Midnight opened the box, her paws rustling through the leaves.",
    "She downloaded the file and ran it.",
    "He killed the process with a single keystroke.",
    "They sent the email at midnight.",
    "Pixel created a small game for fun.",
    "Whiskers launched into the bushes.",
    "It opened the gate and walked through.",
    # describing what the user did, not the assistant
    "You saved the file yesterday.",
    "You opened the file already.",
    # bare past tense without first person — not a claim from the assistant
    "Saved 2,500 tokens.",
    "Wrote 5,000 words.",
    "Killed the runaway process.",
])
def test_no_false_positive(text: str) -> None:
    """Conversational, narrative, and non-first-person claims must NOT trigger."""
    assert _detect_uncalled_claim(text) is None, f"false positive: {text!r}"


def test_patterns_compile() -> None:
    """Every pattern must be a valid regex."""
    import re
    for pat in _CLAIM_PATTERNS:
        re.compile(pat)  # raises on invalid
