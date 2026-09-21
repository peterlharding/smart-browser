"""Smart-Browser bookmarks API."""

__version__ = "0.2.0"

# The API *contract* version -- the `v1` in /api/v1. This is not the release version and
# does not move with it: it changes only when the contract breaks, which should be rare.
# Clients assert it at startup so a mismatch is a clear message rather than a 404 on one
# route. See doc/decisions/0005-versioning-and-compatibility.md.
API_CONTRACT_VERSION = 1
