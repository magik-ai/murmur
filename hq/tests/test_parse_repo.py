"""owner/name out of a remote URL, in every shape a remote can take.

The alias case matters most. An ~/.ssh/config alias hides the real hostname, a
github.com-only pattern returns None for it, and the pre-push guard would then
key claims by the raw URL, match nothing, and wave every push through. A guard
that silently passes is worse than no guard.
"""

import pytest

from hq.util import parse_repo

CASES = [
    # https, with and without the .git suffix
    ("https://github.com/acme/office.git", "acme/office"),
    ("https://github.com/acme/office", "acme/office"),
    # ssh, the scp-like form
    ("git@github.com:acme/office.git", "acme/office"),
    ("git@github.com:acme/office", "acme/office"),
    # ssh through an ~/.ssh/config host alias: no github.com anywhere in it
    ("git@github-acme:acme/office.git", "acme/office"),
    ("github-acme:acme/office", "acme/office"),
    # ssh:// URL form, including through an alias
    ("ssh://git@github.com/acme/office.git", "acme/office"),
    ("ssh://git@github-acme/acme/office.git", "acme/office"),
]


@pytest.mark.parametrize("url,expected", CASES)
def test_parse_repo(url, expected):
    assert parse_repo(url) == expected


@pytest.mark.parametrize("url", ["", "not a url", "/local/path/to/repo"])
def test_parse_repo_gives_up_loudly(url):
    """None, never a guess: the caller turns it into an error the user can read."""
    assert parse_repo(url) is None


def test_every_shape_of_one_remote_keys_the_same_claim():
    """The point of parsing at all: one branch, one claim file, whichever URL
    the machine happens to use for the remote."""
    from hq.claims import claim_path

    paths = {claim_path(parse_repo(url), "main") for url, _ in CASES}
    assert paths == {"claims/acme-office/main.json"}
