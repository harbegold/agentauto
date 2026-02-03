"""Selectors and step detection for the challenge site."""
import re
from typing import Optional

# Step title pattern: "Step X of 30"
STEP_PATTERN = re.compile(r"Step\s+(\d+)\s+of\s+30", re.I)

# Code input: placeholder containing "code" or labels; exclude search/email/comment
CODE_INPUT_SELECTORS = [
    'input[placeholder*="code" i]',
    'input[placeholder*="Code" i]',
    'input[name*="code" i]',
    'input[id*="code" i]',
    'input[aria-label*="code" i]',
    'input[type=text]:not([type=search]):not([name*="email" i]):not([name*="search" i])',
    'input:not([type=hidden]):not([type=search]):not([name*="email" i])',
]

# Submit / proceed buttons (order matters: prefer exact step-advance buttons)
SUBMIT_BUTTON_SELECTORS = [
    'button:has-text("Submit Code")',
    'button:has-text("Proceed Forward")',
    'button:has-text("Next Page")',
    'button:has-text("Next Step")',
    'button:has-text("Proceed")',
    'button:has-text("Advance")',
    'button:has-text("Submit")',
    '[role="button"]:has-text("Submit Code")',
    '[role="button"]:has-text("Proceed Forward")',
    '[role="button"]:has-text("Proceed")',
    '[role="button"]:has-text("Next Page")',
    '[role="button"]:has-text("Advance")',
    'a:has-text("Proceed Forward")',
    'a:has-text("Proceed")',
    'a:has-text("Next Page")',
    'input[type="submit"]',
]

# Decoy buttons that must NOT be used to submit/advance (challenge traps)
DECOY_BUTTON_PATTERN = re.compile(
    r"^(Here!|Button!|Try This!|Click Me!|Continue Reading|Link!)$", re.I
)

# Close / dismiss buttons for popups (including separate popup windows)
CLOSE_BUTTON_TEXTS = [
    "Accept",
    "Close",
    "Dismiss",
    "OK",
    "Continue",
    "Got it",
    "I agree",
    "Decline",
    "No thanks",
    "Maybe later",
    "Not now",
    "No",
    "×",
    "✕",
    "X",
]

# Modal / overlay selectors
MODAL_SELECTORS = [
    "[role=dialog]",
    "[role=alertdialog]",
    ".modal",
    ".popup",
    "[class*='modal']",
    "[class*='popup']",
    "[class*='overlay']",
    ".dialog",
]

# Code reveal / code labels in DOM
CODE_LABEL_PATTERNS = [
    "Reveal Code",
    "Code:",
    "Your code",
    "Step code",
    "Enter code",
    "code to proceed",
]


def parse_step_from_page(text: str) -> Optional[int]:
    """Extract current step number (1-30) from page text."""
    m = STEP_PATTERN.search(text)
    return int(m.group(1)) if m else None


def code_like_token(s: str, min_len: int = 4) -> bool:
    """Heuristic: token that could be a step code (alphanumeric, dash, underscore)."""
    if not s or len(s) < min_len:
        return False
    return bool(re.match(r"^[A-Za-z0-9\-_]+$", s.strip()))
