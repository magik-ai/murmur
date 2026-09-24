"""Take secrets out of text before anyone can read it.

One module, because every place that keeps or shows text a tool printed needs the same rule:
a provider CLI's stderr, the list of models a provider answered with, a dashboard job record.
The rule is exact on purpose. It replaces every secret this farm has stored, and the
handful of token shapes that are unmistakable. It does not guess at "long random-looking
strings", because a commit SHA is one, and a log with every SHA blanked out is useless.
"""
import os
import re

REDACTED = "[redacted]"

TOKEN_SHAPES = re.compile(
    r"sk-ant-[A-Za-z0-9_-]{20,}"          # Anthropic keys and Claude subscription tokens
    r"|gh[pousr]_[A-Za-z0-9]{36,}"        # GitHub classic tokens of every kind
    r"|github_pat_[A-Za-z0-9_]{50,}"      # GitHub fine-grained tokens
    r"|dop_v1_[a-f0-9]{64}"               # DigitalOcean personal access tokens
)

# A stored value shorter than this is not treated as a secret to hunt for: replacing every
# occurrence of "abc" in a log would destroy the log and protect nothing.
MIN_SECRET_LENGTH = 8


# A stored value is replaced only where it stands as a whole token: not preceded or followed by a
# character a token could continue with. A secret that happens to equal the first eight
# characters of a commit SHA, or an ordinary word inside a longer one, must not eat them.
TOKEN_CHAR = r"A-Za-z0-9_\-"


def scrub(text, secrets=()):
    """The text with every stored secret value and every known token shape replaced."""
    if not text:
        return text
    for value in sorted({s for s in secrets if s and len(s) >= MIN_SECRET_LENGTH},
                        key=len, reverse=True):
        pattern = rf"(?<![{TOKEN_CHAR}]){re.escape(value)}(?![{TOKEN_CHAR}])"
        text = re.sub(pattern, REDACTED, text)
    return TOKEN_SHAPES.sub(REDACTED, text)


def stored_secrets(state_dir):
    """Every secret value this farm keeps under $FLEET_STATE/secrets (the keys `fleet models
    auth` stores there), read fresh, empty files skipped."""
    values = []
    root = os.path.join(state_dir, "secrets")
    for folder, _dirs, files in os.walk(root):
        for name in files:
            try:
                with open(os.path.join(folder, name), encoding="utf-8") as handle:
                    value = handle.read().strip()
            except (OSError, UnicodeError):
                continue
            if value:
                values.append(value)
    return values


if __name__ == "__main__":
    import sys
    state = os.environ.get("FLEET_STATE", os.path.expanduser("~/.fleet"))
    known = stored_secrets(state)
    for line in sys.stdin:
        sys.stdout.write(scrub(line, known))
        sys.stdout.flush()
