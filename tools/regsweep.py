#!/usr/bin/env python3
"""regsweep — registry-existence sweep for the method-broadening plan (Phase 2).

Parallel to tools/namesweep.py (which checks NATIVE package names). This tool checks the
*language/app* registries — crates.io, PyPI, npm, Flathub — to find components that could
ALSO offer a universal install method (cargo/pipx/npm/flatpak) they don't list yet, and
verifies each candidate against the registry so we ADD only real, correctly-named methods.

The disambiguator is IDENTITY CONFIRMATION, not name-guessing: a candidate is only "confirmed"
when the registry entry's upstream repository matches the component's own declared GitHub
upstream (from a tarball/native-pkg-file/source binding's `version: { github: … }`). That
kills name-collision risk (npm/pypi/crates all have unrelated same-named packages). Candidates
that plausibly match but can't be identity-confirmed land in a `probable` bucket for human review
rather than being auto-applied.

Usage:
    python tools/regsweep.py [--emit report.json] [--only cargo,flatpak,pipx,npm]
Networked; safe to run anytime. Prints a summary; --emit writes the full JSON report.
"""
import argparse, json, re, sys, time, urllib.request, urllib.error

UA = "configsys-regsweep (https://github.com/; spacemeat@gmail.com)"
_CACHE = {}

def _get(url, is_json=True, method="GET", data=None, timeout=12):
    key = (url, method, data)
    if key in _CACHE:
        return _CACHE[key]
    req = urllib.request.Request(url, method=method,
                                 data=(data.encode() if data else None),
                                 headers={"User-Agent": UA,
                                          "Accept": "application/json",
                                          **({"Content-Type": "application/json"} if data else {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
        out = (json.loads(body) if is_json else body.decode("utf-8", "replace")), r.status
    except urllib.error.HTTPError as e:
        out = None, e.code
    except Exception as e:                                    # network/timeout/json
        out = None, str(e)
    _CACHE[key] = out
    time.sleep(0.25)                                          # be polite to the registries
    return out


# crate/pypi names that differ from the component name (the tool still VERIFIES the repo
# matches the upstream — this only tells it which registry name to look up).
KNOWN_CRATE = {'nushell': 'nu'}

def norm_repo(s):
    """Any forge repo URL / owner-repo string -> lowercased 'owner/repo' (host-prefixed off github)."""
    if not s:
        return None
    s = str(s)
    m = re.search(r'github\.com[/:]([^/]+/[^/#?\s]+)', s)
    if m:
        return m.group(1).lower().removesuffix('.git')
    m = re.search(r'(gitlab\.com|codeberg\.org|git\.sr\.ht)[/:]~?([^/]+/[^/#?\s]+)', s)
    if m:
        return f"{m.group(1)}:{m.group(2)}".lower().removesuffix('.git')
    if re.fullmatch(r'[\w.-]+/[\w.-]+', s):
        return s.lower().removesuffix('.git')  # already owner/repo (github-style)
    return None


# ---- registry probes -------------------------------------------------------

def crates_probe(name):
    """-> (exists, repo_owner/repo or None)."""
    d, st = _get(f"https://crates.io/api/v1/crates/{name}")
    if st != 200 or not d:
        return False, None
    cr = d.get("crate", {})
    return True, norm_repo(cr.get("repository") or cr.get("homepage"))


def pypi_probe(name):
    d, st = _get(f"https://pypi.org/pypi/{name}/json")
    if st != 200 or not d:
        return False, None, False
    info = d.get("info", {})
    urls = " ".join(str(v) for v in (info.get("project_urls") or {}).values())
    urls += " " + str(info.get("home_page") or "")
    # console_scripts presence isn't in the JSON API; approximate "is an app" via keywords later
    return True, norm_repo(urls), True


def npm_probe(name):
    d, st = _get(f"https://registry.npmjs.org/{urllib.parse.quote(name, safe='@/')}")
    if st != 200 or not d:
        return False, None
    repo = d.get("repository")
    if isinstance(repo, dict):
        repo = repo.get("url")
    return True, norm_repo(repo)


def flathub_search(query):
    d, st = _get("https://flathub.org/api/v2/search", method="POST",
                 data=json.dumps({"query": query}))
    return (d or {}).get("hits", []) if st == 200 else []


def flathub_urls(app_id):
    d, st = _get(f"https://flathub.org/api/v2/appstream/{app_id}")
    if st != 200 or not d:
        return None
    u = d.get("urls") or {}
    return {"homepage": u.get("homepage"), "vcs": u.get("vcs_browser"), "name": d.get("name")}


# ---- candidate generation --------------------------------------------------

import urllib.parse  # noqa: E402


def load_catalog():
    from configsys.app import Context, build_parser
    r = Context(build_parser().parse_args(['--home', '/tmp/nohome', '--os', 'pop', 'inspect'])).routes
    out = []
    for name, c in r.components.items():
        if name.endswith(('-dotfiles', '-service', '-group')):
            continue
        vias, github, crates, pypi, names = set(), None, None, None, {}
        for b in c.bindings:
            vias.add(b.via)
            d = b.details or {}
            ver = d.get('version') or {}
            if isinstance(ver, dict):
                github = github or norm_repo(ver.get('github')) or norm_repo(ver.get('url')) or norm_repo(ver.get('repo'))
                crates = crates or ver.get('crates')
                pypi = pypi or ver.get('pypi')
            github = github or norm_repo(d.get('repo'))
            nm = d.get('name')
            if isinstance(nm, str):
                names[b.via] = nm
        out.append(dict(name=name, attrs=c.attrs or [], vias=sorted(vias), github=github,
                        crates=crates, pypi=pypi, names=names, desc=(c.description or '')))
    return out


def cand_names(comp, via):
    """crate/pypi/npm names to try for a component, most-likely first."""
    seen, res = set(), []
    for n in (KNOWN_CRATE.get(comp['name']) if via == 'cargo' else None,
              comp['names'].get(via), comp.get('crates') if via == 'cargo' else None,
              comp.get('pypi') if via in ('pipx', 'pip') else None, comp['name']):
        if n and n not in seen:
            seen.add(n); res.append(n)
    return res


def sweep(catalog, only):
    confirmed, probable, rejected = [], [], []

    def want(via):
        return not only or via in only

    for c in catalog:
        vias = set(c['vias'])
        gh = c['github']

        # ---- cargo (Rust tools) ----
        if want('cargo') and 'cargo' not in vias and (gh or c['crates']):
            hit = None
            for nm in cand_names(c, 'cargo'):
                exists, repo = crates_probe(nm)
                if exists:
                    hit = (nm, repo); break
            if hit:
                nm, repo = hit
                if c['crates'] or (gh and repo == gh):
                    confirmed.append(dict(comp=c['name'], via='cargo', name=nm,
                                          why=f"crate repo {repo} == upstream {gh}" if gh else "declared crates: source"))
                elif repo:
                    probable.append(dict(comp=c['name'], via='cargo', name=nm,
                                         why=f"crate exists but repo {repo} != upstream {gh}"))
                else:
                    probable.append(dict(comp=c['name'], via='cargo', name=nm,
                                         why=f"crate '{nm}' exists but has no repo to confirm vs {gh}"))
            else:
                rejected.append(dict(comp=c['name'], via='cargo', why="no matching crate"))

        # ---- pipx (Python CLIs) ----
        if want('pipx') and not ({'pip', 'pipx'} & vias) and (gh or c['pypi']):
            hit = None
            for nm in cand_names(c, 'pipx'):
                exists, repo, _ = pypi_probe(nm)
                if exists:
                    hit = (nm, repo); break
            if hit:
                nm, repo = hit
                if c['pypi'] or (gh and repo == gh):
                    confirmed.append(dict(comp=c['name'], via='pipx', name=nm,
                                          why=f"pypi urls -> {repo} == upstream {gh}" if gh else "declared pypi: source"))
                else:
                    probable.append(dict(comp=c['name'], via='pipx', name=nm,
                                         why=f"pypi '{nm}' exists but repo {repo} != upstream {gh}"))

        # ---- flatpak (GUI apps) — flatpak is IN the preference list, so no not-listed tie ----
        if want('flatpak') and 'GUI' in c['attrs'] and 'flatpak' not in vias:
            hits = flathub_search(c['name'])
            best = None
            for h in hits:
                if h.get('type') != 'desktop-application':
                    continue
                hn = (h.get('name') or '').lower()
                cn = c['name'].lower().replace('-', ' ')
                exact = hn == cn or hn == c['name'].lower() or h.get('app_id', '').lower().split('.')[-1] == c['name'].lower()
                if exact:
                    best = h; break
            if best:
                app = best['app_id']
                u = flathub_urls(app) or {}
                repo = norm_repo(u.get('vcs')) or norm_repo(u.get('homepage'))
                verified = best.get('verification_verified')
                if (gh and repo == gh) or verified:
                    confirmed.append(dict(comp=c['name'], via='flatpak', app=app,
                                          why=("upstream repo match " if (gh and repo == gh) else "") +
                                              ("flathub-verified" if verified else "")))
                else:
                    probable.append(dict(comp=c['name'], via='flatpak', app=app,
                                         why=f"name match '{best.get('name')}' but unverified & no repo confirm"))
            elif hits:
                probable.append(dict(comp=c['name'], via='flatpak', app=None,
                                     why=f"flathub hits but no exact name match (top: {hits[0].get('app_id')})"))

    return dict(confirmed=confirmed, probable=probable, rejected=rejected)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--emit')
    ap.add_argument('--only', help="comma list: cargo,pipx,flatpak")
    a = ap.parse_args()
    only = set(a.only.split(',')) if a.only else None
    cat = load_catalog()
    rep = sweep(cat, only)
    if a.emit:
        json.dump(rep, open(a.emit, 'w'), indent=2)
    print(f"confirmed={len(rep['confirmed'])}  probable={len(rep['probable'])}  rejected={len(rep['rejected'])}")
    print("\n== CONFIRMED (safe to auto-add) ==")
    for r in rep['confirmed']:
        tgt = r.get('name') or r.get('app')
        print(f"  {r['comp']:22} +{r['via']:8} {tgt:38} {r['why']}")
    print("\n== PROBABLE (needs human eyes) ==")
    for r in rep['probable']:
        tgt = r.get('name') or r.get('app') or '—'
        print(f"  {r['comp']:22} +{r['via']:8} {str(tgt):38} {r['why']}")


if __name__ == '__main__':
    main()
