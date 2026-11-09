'''failures.py — a small shared taxonomy for classifying external driver stumbles.

Drivers and the native index-refresh step map raw tool output into a CATEGORY + a plain-language
REMEDIATION hint, so a failure renders uniformly (report / TUI / refresh) instead of as an opaque
dump. Classification decides how we explain a failure, and whether retry_transient retries it
(DEFINITIVE categories aren't retried) — so a misread category costs retries as well as words.

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

# An HTTP status as the tools print it — curl/git "returned error: 404", dnf "Status code: 404",
# "HTTP/1.1 404", python's "HTTP Error 404", wget "ERROR 404", a bare "curl: (22) … 404" — so a 404/403
# is read from the status, never from any "404" token ("failed to build at line 404").
_HTTP_STATUS = r'(?:Status code:|returned error:|HTTP Error|HTTP/[0-9.]+|ERROR|curl: \(22\)[^\n]*?)\s*'

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
    (re.compile(r'returned error: 5[0-9][0-9]\b|\b50[234] (?:Bad Gateway|Service Unavailable|Gateway Time-?out)',
                re.I), NETWORK,
     "the upstream server answered with an error of its own (HTTP 5xx) — usually brief; retry later."),
    # an HTTP 404/403 BEFORE the generic download-failed rule: apt's "Failed to fetch … 404  Not Found"
    # (a stale index) and dnf's "Cannot download repomd.xml: Status code: 404" (a vendor repo with no
    # tree for a new release yet) are definitive, not a network blip worth three retries
    (re.compile(_HTTP_STATUS + r'404\b|\s404\s+Not Found'), NOT_FOUND,
     "an upstream URL is gone (moved or removed) — the component's route likely needs updating."),
    (re.compile(_HTTP_STATUS + r'403\b|\s403\s+Forbidden'), AUTH,
     "the server refused access (HTTP 403) — a private repo or download needs credentials, or the "
     "URL/token is wrong or rate-limited."),
    (re.compile(r'Failed to fetch|Cannot download|Curl error|could not download', re.I), NETWORK,
     "a download failed (network, or the upstream URL is unavailable) — retry, or the route may "
     "need updating if the URL moved."),
    # a shell's "brew: command not found" (bash) / "sh: 1: brew: not found" (dash): the step's own tool
    # isn't on PATH — before the generic "Not Found" rule below, which matches case-sensitively so
    # this and pacman's "target not found" aren't read as a vanished URL
    (re.compile(r'command not found|^\S*sh: (?:line )?\d+: \S+: not found', re.M), DEPENDENCY,
     "a command this step runs isn't installed, or isn't on PATH — install it (or open a new shell "
     "so its PATH setup applies) and retry."),
    (re.compile(r'(?-i:Not Found)|No such file or directory.*http|does not have a Release file', re.I),
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
