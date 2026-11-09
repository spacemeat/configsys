'''help.py — the per-screen `?` pages (_HELP: each screen's description + glossary).

Split out of menu.py (review-2026-11-2 D2).
'''



# Per-page `?` help: a brief description + a glossary of the terms/markers/glyphs that page uses.
# (Keybindings are generated from the live keymap; these are the reminders that aren't keys.)
def _provides_legend():
    '''The Plugins `?` legend for the provides column: one (code, meaning) row per provision.'''
    from .. import plugins
    return [(f'  {c}', label) for _k, c, label in plugins.PROVISIONS]


_PROVIDES_LEGEND = _provides_legend()


_HELP = {
    'components': {
        'desc': "This machine's picks, as a tree. Each row is a component (or a unit under it) with its "
                "install driver, scope, status, and installed/latest versions. Stage operations on rows, "
                "then run them with the execute key.",
        'glossary': [
            ('view (M)', 'to-do (the default: tracked components missing, outdated or with a routing '
                         'status — switch / unmet / dangling — plus installed ones staged for uninstall) · tracked (all of this machine\'s picks) · '
                         'installed+tracked (also installed components you haven\'t tracked)'),
            ('status', 'installed · outdated (newer available) · missing · locked (version held) · '
                       'partial (some units installed) · unsupported (no driver for its method here) · '
                       'untrusted (its driver comes from a plugin you haven\'t trusted) · error (a probe '
                       'or op failed)'),
            ('routing status', 'shown instead of the version status: switch (installed via a method '
                               'routes no longer offer here; i swaps it out) · unmet (installable only '
                               'with a driver you disabled, directly or through what it needs) · '
                               'dangling (no install method on this OS)'),
            ('op badges', 'I install · U upgrade · X remove · L lock · l unlock · * mixed — staged, run '
                          'with execute. ✗ marks a failed op; » a selected row'),
            ('make current (i / I)', 'install if missing, upgrade if outdated, swap out a switch row\'s '
                                     'stranded install. i is the cursor/selection, I every tracked '
                                     'component (a row already staged — e.g. a remove from !uninstall '
                                     '— is left as is). u/U upgrade outdated only'),
            ('tree', '▾/▸ expand/collapse. Components group under the profile that defines them '
                     '((other) = none); a component opens to its units — itself plus what it requires'),
            ('System Updates', 'packages with pending updates outside your picks — from this OS\'s '
                               'package manager, flatpak and snap — by tier (kernel, core, standard, '
                               'apps); auto-pulled ones are dimmed. i/u stages them all, '
                               'c on any of them unstages them all (all or nothing), the execute key '
                               'applies them in bulk. R rescans them'),
            ('header', 'view mode · package-index age (refresh with R) · ⚠ reboot advised · your '
                       'primary plugin\'s ↑N to push / ↓N to sync · ⟳ N system updates · ⚠ N issues '
                       '(! to view)'),
            ('scope', 'user (~, no sudo) vs system (/opt, needs sudo)'),
            ('[L]', 'beside an installed version: the version is locked'),
            ('also present', 'on the detail line: another install of this component via a different '
                             'method — pin it (v) to adopt it, or swap it out'),
            ('[R] recipe pin', 'beside LATEST: the method builds a version its route pins, and '
                               'upstream has released newer. u rebuilds the same pin; the new release '
                               'needs a route change. The detail line names both versions.'),
        ],
    },
    'profiles': {
        'desc': "The component × machine matrix. Left: profiles as a BROWSE LENS — the repo's, your "
                "plugins' and your own — page through them to discover components. Right: a table of the components, with a column "
                "per machine. Mark what you want per machine; each machine installs exactly its picks.",
        'glossary': [
            ('columns', "per row: # multi-selected · name · via (resolved install method; [pinned]) · "
                        "from (origin: repo / plugin / local) · inst'd (● installed+tracked / "
                        '⊙ installed+untracked [dimmed when orphans-ignore lists it] / ◐ partial: some parts, or a required component '
                        'missing / ○ none / ⮾ staged for uninstall / ⊘ no install method on this OS) · '
                        'new ◆ · flag ☆ interesting / · seen · then one Included cell per machine '
                        '(● tracked / ○ not)'),
            ('track (T / t)', 'T toggles TRACKING of the multi-select set / the whole selected profile; '
                              't (or ⏎) toggles just the HIGHLIGHTED component. Tracking = Included on the '
                              'TARGET machines (see M), and also marks the component seen.'),
            ('machines (M)', 'choose the TARGET machines (plural) T/t fan out to — toggle each; the modal '
                             'also adds / renames / removes machines. Target headers are highlighted.'),
            ('multi-select', 'space toggles a component into the set (#); a (select-all) takes every row '
                             'in view — or, in the browse pane, the whole profile’s members. T then tracks '
                             'the whole set.'),
            ('parts (▸ / ▾)', 'a `via: parts` aggregator (docker, vulkan-runtime) shows a ▸ twisty — ⏎ drills '
                              'it open to its pieces (indented ↳), each an ordinary component you can track '
                              '(t) or pin a method for (v). The infobox lists them (and a component’s '
                              'requires:) with each’s resolved method, so you see the composition first.'),
            ('scroll', '↑/↓ move · ←/→ scroll the pane horizontally when it overflows (a thumb shows on '
                       'the bottom border); in the browse pane ←/→ first fold/unfold the include tree.'),
            ('interesting / seen', 'i toggles INTERESTING (☆, a flag) on the highlighted component; s '
                                   'toggles NEW ↔ SEEN (·) — never clears a flag. I / S set them across the '
                                   'multi-select set / whole profile. Tracking (T/t) also marks seen. Kept '
                                   'for this box, not per machine column.'),
            ('mark all seen (E)', 'acknowledge every remaining NEW component at once (confirms first) — '
                                  'clears the ◆s after a triage pass; leaves seen/interesting flags alone'),
            ('claim (C)', 'track every component already INSTALLED on this box onto the target machine(s) '
                          '— adopt an existing system into a fresh configsys (confirms first)'),
            ('!all / !uninstall', '!all (top) lists EVERY component — the whole catalog; !uninstall '
                                  '(last) lists what x staged for removal; any other profile scopes the '
                                  'table to its own members (▸ marks the shown one)'),
            ('⁺N / ☆N / ⊙N', 'on a browse profile (left): ⁺N = NEW members · ☆N = INTERESTING members · '
                             '⊙N = installed-here-but-UNTRACKED members (claimable) — the profile’s triage signal'),
            ('row colours', 'the name is tinted by state: NEW in the new-accent colour · INTERESTING in '
                            'the link colour · SEEN dimmed · unavailable-here greyed · installed UNDERLINED'),
            ('install overlay (O)', "toggles the install axis: the inst'd column and the installed "
                                    "underline (off, inst'd reads ○). On by default (the install-overlay "
                                    'setting). . ignores / un-ignores the cursor orphan'),
            ('attr-filter (f)', 'faceted kind filter over the catalog (F = live substring filter)'),
            ('via (v) / machines (m)', 'v pins the selected component’s install method; m opens a '
                                       'machines dialog for JUST the cursor component (toggle its '
                                       'tracking per machine) · x stages it for uninstall'),
            ('detail box', 'on a browse profile (left): its raw .hu definition. On a component '
                           '(right): description · ⊘ where it installs, if not here · parts or requires '
                           '(each with its method) · attrs · required-by · in-profiles'),
        ],
    },
    'plugins': {
        'desc': "Data/code plugins declared in your config. Top: the plugin tree. Bottom: the review "
                "diff for the selected plugin, fetched as the cursor settles. Sync, bless, trust, lock "
                "and update from here.",
        'glossary': [
            ('columns', 'name · source · ref (pinned) · remote-ref (upstream: green = current, amber = '
                        'update available) · abi · code · provides'),
            ('provides', 'what the plugin ships, one code each (its manifest `provides:` until synced):'),
            *_PROVIDES_LEGEND,
            ('diff', 'synced: your copy → the remote-ref (what u would pull in). Not synced: the ref → '
                     'the remote-ref, or everything a sync would download — fetched into a review '
                     'cache that is never loaded, so you can read it before you sync'),
            ('↑ ↓ ●', 'on your ★ primary\'s remote-ref: ↑N changes not pushed yet, ↓N changes from your '
                      'other machines (s syncs them in), ● edits not committed yet. Both ↑ and ↓ = the '
                      'two sides need combining, which P does'),
            ('P push', 'publish your ★ primary: commit, combine with what your other machines pushed '
                       '(a file both changed is asked about: keep this machine\'s, keep the other\'s, or '
                       'edit both), then push. Edits you made by hand are only included if you say so. '
                       'The primary-push setting decides whether quitting offers it (ask), does it '
                       '(auto; auto-on-quit also on Q) or leaves it to you (manual)'),
            ('H history', 'your ★ primary\'s recent changes, newest first (↑ not pushed yet, * made by '
                          'configsys), with "Undo" for the newest change configsys made: dropped if it '
                          'was never pushed, else taken back by a new commit (undo again to redo)'),
            ('⊘ locked', 'L locks the plugin on this machine: no sync, update, bless or trust until L '
                         'unlocks it. A synced copy keeps loading as it is — x removes it'),
            ('abi', "ok, or ≠N: the plugin needs ABI N — an incompatible plugin is skipped, not loaded"),
            ('code', 'trust for its Python code or command-carrying recipes: trusted · untrusted · '
                     'changed (content moved; trust again) · unsynced · — (nothing to trust)'),
            ('dimmed row', 'not synced, ABI-incompatible, or quarantined (content fails its sha256)'),
            ('★ primary', 'your primary plugin (b blesses one, B clears it) — may set machine settings '
                          'and travels to your machines'),
            ('tree', '├─ a transitive plugin (declared by another plugin, not your top config)'),
        ],
    },
    'glue': {
        'desc': "Shell-integration snippets (PATH, aliases, env, completions) for your components, "
                "grouped by installed shell. Each shell heads its group with its conf.d loader status. "
                "A ship→activate toggle — glue is shipped, never captured.",
        'glossary': [
            ('active', 'linked into ~/.config/<shell>/conf.d and sourced by the shell — done.'),
            ('changed', 'active, but the shipped snippet has changed since — A re-activates it.'),
            ('available', 'shipped but not linked yet — activate (a) to enable it.'),
            ('empty', 'no snippet source found for this shell — nothing to activate.'),
            ('shell groups', "each installed shell heads a group; its header shows the conf.d loader: "
                             "active, inactive, or not wired (bash rides ~/.bash_aliases, zsh an "
                             "~/.zshrc block, fish sources conf.d natively, elvish/nushell inline a "
                             "block into their rc file)."),
            ('activate (a / A)', "a enables the current snippet for ITS shell (the group it's under); A "
                                 "(re)activates the WHOLE shell group — enabling available snippets AND "
                                 "refreshing changed ones from source. Activating also wires the "
                                 "loader. x deactivates this shell's link."),
        ],
    },
    'dotfiles': {
        'desc': "Your via:dotfiles CONFIG — the files configsys links into place and syncs to your "
                "store. Each row: the component, its state, the ~/ location, and where the managed "
                "content lives. Manage (m) captures on-system config and links it in one step.",
        'glossary': [
            ('managed', 'configsys manages this config — the symlink is live and your edits sync to '
                        'your store. Nothing to do (u unmanages it).'),
            ('unmanaged', 'not managed yet: either a real on-system file to capture, or content already '
                          'stored/shipped that just needs linking — manage (m or ⏎) does either. The '
                          'source column shows where the content lives or will land.'),
            ('no config', "nothing here yet — no stored content and no on-system file (a personal "
                          "dotfile you haven't made or adopted). Manage it once you have one."),
            ('! at risk', 'a real on-system file configsys does NOT manage yet (e.g. your existing '
                          '~/.config/nvim). Managing it adopts + backs it up; until then a plain link '
                          'would refuse to overwrite it.'),
            ('manage (m)', 'adopt any on-system config into your store AND symlink it into place — one '
                           'step. A pre-existing real file is first backed up to <dst>.pre-configsys.'),
            ('manage all (M)', 'manage every unmanaged config at once.'),
            ('unmanage (u / U)', "remove configsys's symlink and restore any backup — your content "
                                 "stays in your store. u unmanages the current row, U every managed "
                                 "one; both ask to confirm first."),
            ('source', "where the managed content lives: <plugin> travels to your machines (in your "
                       "primary plugin), <local> is this box only, <repo> is a shipped default, "
                       "<name> is shipped by that plugin."),
            ('move store (s / S)', "move a config between stores: s toggles the current one "
                                   "<local>↔<plugin> (and normalizes any legacy layout); S opens a "
                                   "chooser to move ALL configs to the plugin or local."),
        ],
    },
    'config': {
        'desc': "Machine settings. Each row: the setting, its value, whether it's the built-in default, "
                "and where it's stored (edits land there), with what it does below. Enter to edit; some "
                "open a picker.",
        'glossary': [
            ('default', 'default (built-in) · custom (you set it) · env (an environment variable wins)'),
            ('store', "a plugin name (primary plugin — travels to your machines) · a path (machine-local "
                      "— this box only) · an env var (env override). Highlighted when not the setting's "
                      "natural home."),
            ('move', 'relocate a setting between machine-local and your primary plugin'),
            ('scope', 'user (~) vs system (/opt) — the default install location'),
        ],
    },
    'theme': {
        'desc': "Live theme editor. Left: the shared color map (name → #rrggbb), then the focused "
                "page's role styles. Right: a live sample of the selected page. Edits apply and save "
                "instantly; s exports a theme pack or promotes the full look to your primary plugin.",
        'glossary': [
            ('map', 'shared colors; a role references one by name, or uses a literal #rrggbb'),
            ('fx', 'per-role bold / underline / reverse'),
            ('sample', 'F1-F7 pick which page the sample previews'),
            ('gradient', "each page's diagonal background; toggle per page. Its colors are the "
                         "gradient from / to rows at the end of the role list"),
            ('*', 'a color, role or gradient end you changed from the default (reset restores it)'),
        ],
    },
}
