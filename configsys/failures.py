'''failures.py — a small shared taxonomy for classifying external driver stumbles.

Drivers and the native index-refresh step map raw tool output into a CATEGORY + a plain-language
REMEDIATION hint, so a failure renders uniformly (report / TUI / refresh) instead of as an opaque
dump. Classification is purely advisory — it never changes control flow, only how we explain it.

The signature table is deliberately conservative: an unrecognised failure stays (None, None) and is
shown verbatim, exactly as before. Add rows as real-world stumbles teach us their fingerprints.
'''

import re
import time

# Stable category identifiers (recorded in failure records + shown in rendering).
NETWORK = 'network-unreachable'
AUTH = 'auth/permission'
SIGNATURE = 'signature/trust'
NOT_FOUND = 'not-found/moved'
DEPENDENCY = 'dependency-missing'
BUILD = 'build-failed'
PARTIAL = 'partial-state-left'

CATEGORIES = (NETWORK, AUTH, SIGNATURE, NOT_FOUND, DEPENDENCY, BUILD, PARTIAL)

# (compiled pattern, category, remediation-template). First match wins, so order most-specific
# first. `remediation` is .format()'d with the match's capture groups (e.g. a NO_PUBKEY key id).
_RULES = [
    (re.compile(r'NO_PUBKEY\s+([0-9A-Fa-f]{8,})'), SIGNATURE,
     "a repository is signed by key {0}, which isn't in the trusted keyring — the signing key "
     "rotated or was never imported. Re-import the current key or remove the stale source."),
    (re.compile(r'following signatures couldn.t be verified|is not signed|GPG error', re.I), SIGNATURE,
     "a repository failed signature verification (a missing or rotated signing key). Re-import "
     "its key, or remove the source if it's no longer wanted."),
    (re.compile(r'repomd\.xml.*(?:GPG|NOKEY)|GPG check FAILED|NOKEY', re.I), SIGNATURE,
     "a dnf/zypper repo's metadata is signed by an untrusted key — re-import the repo key or "
     "remove the repo."),
    (re.compile(r'Could not resolve|Temporary failure in name resolution|Network is unreachable|'
                r'Connection timed out|Failed to connect|Cannot download.*Timeout', re.I), NETWORK,
     "a network fetch failed — check connectivity/proxy and retry."),
    (re.compile(r'Failed to fetch|Cannot download|Curl error|could not download', re.I), NETWORK,
     "a download failed (network, or the upstream URL is unavailable) — retry, or the route may "
     "need updating if the URL moved."),
    (re.compile(r'\b404\b|Not Found|No such file or directory.*http|does not have a Release file', re.I),
     NOT_FOUND,
     "an upstream URL is gone (moved or removed) — the component's route likely needs updating."),
    (re.compile(r'Permission denied|are you root|must be (?:run as |)root|sudo:.*(?:password|required)|'
                r'\bEACCES\b', re.I), AUTH,
     "a privileged step was denied — re-run so the sudo prompt can be answered."),
    (re.compile(r'Unable to locate package|[Nn]o such package|Package [^ ]+ (?:not|isn.t) '
                r'(?:found|available)|target not found|No package [^ ]+ available', re.I), DEPENDENCY,
     "the package name didn't resolve in this OS's repos — likely a per-distro name drift "
     "(run the podman name sweep to confirm)."),
    (re.compile(r'make(?:\[[0-9]+\])?:\s*\*\*\*|compilation terminated|error: linker|'
                r'undefined reference to|fatal error:.*No such file', re.I), BUILD,
     "a from-source build failed — check the toolchain and dev-lib `requires:` for this component."),
]


def classify(text):
    '''(category, remediation) for raw tool output, or (None, None) if unrecognised. The
    remediation is formatted with the matched pattern's capture groups (e.g. the key id).'''
    if not text:
        return None, None
    for pat, cat, hint in _RULES:
        m = pat.search(text)
        if m:
            try:
                return cat, hint.format(*m.groups())
            except (IndexError, KeyError):
                return cat, hint
    return None, None


# A failure whose category is DEFINITIVE won't change on a retry — it names a specific repo/package
# (a rotated key, a 404'd URL, a permission wall, an unresolved name). Everything else — a network
# blip, or an unrecognised stumble like apt's "E: The list of sources could not be read" from a
# concurrent package-manager run — is treated as possibly TRANSIENT and worth a retry.
DEFINITIVE = (SIGNATURE, NOT_FOUND, AUTH, DEPENDENCY)


def retry_transient(run, *, tries=3, backoff=1.5, sleep=time.sleep):
    '''Call `run()` (which returns a Result), retrying while the failure looks TRANSIENT — up to
    `tries` attempts with `backoff` seconds between. A DEFINITIVE failure returns on the first try (a
    retry can't help). So a momentary package-manager hiccup self-heals instead of surfacing as a
    scary failure, while a real problem still reports promptly. Returns the final Result. `sleep` is
    injectable for tests.'''
    res = run()
    for _ in range(1, max(1, tries)):
        if res.ok or classify(res.output)[0] in DEFINITIVE:
            return res
        sleep(backoff)
        res = run()
    return res
