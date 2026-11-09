'''cli/plugin.py — `configsys plugin …` — list/sync/add/remove/bless/trust/lock/update/diff/push/log/undo,
`plugin init` and `set-source`, and the CLI side of the primary push questions.

Split out of app.py (review-2026-11-2 D2).
'''

import argparse
import os
import sys
from pathlib import Path
from .. import primarygit
from ..drivers import get_driver
from .where import active_snapshot, print_sync_delta


def _fmt_conflict(kind, name, dirs):
    return f"conflict: {kind} '{name}' claimed by plugins {', '.join(dirs)} (last declared wins)"


def _git_init_commit(ctx, d, msg):
    '''git init + add + commit in `d` (via the runner, so --pretend prints). Non-fatal: a failed
    commit (e.g. no git identity configured) leaves the repo + files in place — reported.'''
    import shlex
    dq = shlex.quote(str(d))
    ctx.runner.run(f'git -C {dq} init -q -b main', capture=False)
    ctx.runner.run(f'git -C {dq} add -A', capture=False)
    r = ctx.runner.run(f'git -C {dq} commit -q -m {shlex.quote(msg)}', capture=False)
    if r is not None and not r.ok:
        print('  note: git commit skipped — set git user.name/email, then commit in the plugin dir')


def _sweep_glue_to_primary(ctx, plug, dry_run, force):
    '''Move the user's LOCAL glue into the primary plugin's glue/ so it travels: the authoring subtree
    `<store>/shell/**` (your user.d snippets + `glue override` forks) plus the overrides manifest.
    Skips the deploy mirror (`<store>/<shell>/conf.d/` — a regenerated cache). Returns (moved, skipped
    rel-paths). Idempotent-ish: an entry already in the primary is skipped unless `force`.'''
    import json as _json
    import shutil
    src_root = getattr(ctx.paths, 'user_glue_dir', None)
    if src_root is None:
        return 0, []
    src_root = Path(src_root)
    dest_glue = plug / 'glue'
    if not dry_run:
        primarygit.will_write(dest_glue)
    moved, skipped = 0, []
    src_shell = src_root / 'shell'
    files = sorted(f for f in src_shell.rglob('*') if f.is_file()) if src_shell.is_dir() else []
    for f in files:
        rel = f.relative_to(src_root)                    # shell/<shell>/...  (user.d + overrides)
        dst = dest_glue / rel
        if dst.exists() and not force:
            skipped.append(str(rel))
            continue
        moved += 1
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), str(dst))
    man = src_root / 'glue-overrides.json'               # merge the drift manifest (local wins on a tie)
    if man.is_file():
        moved += 1
        if not dry_run:
            dstman = dest_glue / 'glue-overrides.json'
            merged = {}
            for m in (dstman, man):
                try:
                    merged.update(_json.loads(m.read_text(encoding='utf-8')))
                except (OSError, ValueError):
                    pass
            dstman.parent.mkdir(parents=True, exist_ok=True)
            dstman.write_text(_json.dumps(merged, sort_keys=True), encoding='utf-8')
            man.unlink()
    if not dry_run and src_shell.is_dir():               # tidy now-empty dirs left by the moves
        for d in sorted((p for p in src_shell.rglob('*') if p.is_dir()), reverse=True):
            try:
                d.rmdir()
            except OSError:
                pass
        try:
            src_shell.rmdir()
        except OSError:
            pass
    return moved, skipped


def _redeploy_user_glue(ctx):
    '''Re-link the user.d namespace for every installed glue shell — after a sweep MOVES the sources
    into the primary, the conf.d links (which point straight at the layer file) must repoint there.'''
    try:
        drv = get_driver('glue', ctx.runner, ctx.paths)
        for shell in drv.installed_shells():
            drv.deploy_user_glue(shell)
    except Exception:                                    # noqa: BLE001 — never fail init on a relink
        pass


def cmd_plugin_init(ctx, args, decls):
    '''Assemble a personal PRIMARY plugin from local bits (captured dotfiles + profiles/components
    + your other plugins as transitive), or merge them into an existing primary.'''
    from .. import plugins
    ctx.ensure_user_config()
    prim = plugins.primary_name(decls)
    return _plugin_init_merge(ctx, args, prim) if prim else _plugin_init_create(ctx, args, decls)


def _repoint_dotfile_links(ctx, old_root, new_root):
    """After the dotfiles store moved from `old_root` to `new_root`, re-point every LIVE link into it
    (each picked dotfiles component's targets) at the same file under the new root — they used to
    dangle after `plugin init` (B9). Returns the count re-pointed. Best-effort per link."""
    from ..drivers import get_driver
    old, new = os.path.realpath(str(old_root)), str(new_root)
    df = get_driver('dotfiles', ctx.runner, ctx.paths)
    if df is None:
        return 0
    try:
        units, _errs = ctx.routes.resolve_resilient(list(ctx.config.requested()))
    except Exception:                                  # noqa: BLE001
        return 0
    n = 0
    for rc in units.values():
        if rc.driver != 'dotfiles':
            continue
        for _src, tgt, _absorb in df.pairs(rc):
            try:
                if not tgt.is_symlink():
                    continue
                dest = os.readlink(tgt)
                full = os.path.normpath(os.path.join(os.path.dirname(str(tgt)), dest))
                if not (full == old or full.startswith(old.rstrip(os.sep) + os.sep)):
                    continue
                moved = os.path.join(new, os.path.relpath(full, old))
                if os.path.lexists(moved):
                    tgt.unlink()
                    tgt.symlink_to(moved)
                    n += 1
            except OSError:
                continue
    return n


def _plugin_init_create(ctx, args, decls):
    import getpass
    import shutil
    from .. import plugins
    name = args.name or f'configsys-{getpass.getuser()}'
    plug = ctx.paths.plugins_dir / name
    if plug.exists():
        print(f'configsys: {plug} already exists — pick another name (`configsys plugin init <name>`), or remove it first')
        return 1
    store = ctx.paths.user_dotfiles_dir
    store_entries = sorted(store.iterdir()) if store.exists() else []
    sections = plugins.config_sections_text(ctx.paths.user_config_file, ('profiles', 'components'))

    print(f'plugin init: create personal primary plugin "{name}"')
    print(f'  at          {plug}')
    gmoved_est, _gskip = _sweep_glue_to_primary(ctx, plug, dry_run=True, force=args.force)
    print(f'  dotfiles    {len(store_entries)} item(s) moved from {ctx.paths.user_dotfiles_dir}')
    print(f'  glue        {gmoved_est} user snippet/override(s) moved from {ctx.paths.user_glue_dir}')
    print(f'  config      {", ".join(sections) or "(none)"} copied from configsys.hu')
    print(f'  transitive  {len(decls)} plugin(s) carried into the manifest')
    if args.dry_run or ctx.runner.pretend:
        print('\n(' + ('dry run' if args.dry_run else '--pretend') + ' — nothing written)')
        return 0

    plugins.scaffold_primary(plug, name, decls, sections)     # decls = the (non-primary) others
    dfdir = plug / 'dotfiles'
    for entry in store_entries:
        shutil.move(str(entry), str(dfdir / entry.name))
    relinked = _repoint_dotfile_links(ctx, store, dfdir) if store_entries else 0
    gmoved, _ = _sweep_glue_to_primary(ctx, plug, dry_run=False, force=args.force)
    if gmoved:                                            # repoint user.d links at the new primary
        ctx.paths.primary_glue_dir = plug / 'glue'
        _redeploy_user_glue(ctx)
    (plug / '.gitignore').write_text('__pycache__/\n', encoding='utf-8')
    (plug / 'README.md').write_text(
        f'# {name}\n\nA personal [configsys](https://github.com/spacemeat/configsys) plugin '
        f'(dotfiles + profiles/components). Authored locally by `configsys plugin init`. To share '
        f'it, create an empty repository, then run `configsys plugin set-source {name} '
        f'github:you/{name}` and `configsys plugin push`.\n',
        encoding='utf-8')
    _git_init_commit(ctx, plug, 'initial personal config (configsys plugin init)')
    plugins.set_declared(ctx.paths.user_config_file,      # follows its branch (never tagged)
                         [{'source': str(plug), 'ref': 'main', 'primary': True}])
    # the copied sections now live in the plugin (primary layer) — strip the redundant originals
    # from configsys.hu so it collapses toward the one-line bootstrap the primary model is for.
    stripped = plugins.remove_sections(ctx.paths.user_config_file, list(sections)) if sections else []
    print(f'\nconfigsys: created + blessed "{name}" as your primary plugin.')
    if relinked:
        print(f'  ({relinked} linked config(s) re-pointed at the plugin\'s copy.)')
    if stripped:
        print(f'  ({", ".join(stripped)} moved into the plugin and removed from configsys.hu.)')
    print('  capture now lands in it. When ready to share, create an empty repository for it')
    print(f'  (e.g. `gh repo create {name} --private`), then:')
    print(f'    configsys plugin set-source {name} github:you/{name}')
    print('    configsys plugin push')
    return 0


def _plugin_init_merge(ctx, args, prim):
    import shutil
    from .. import plugins
    plug = ctx.paths.plugins_dir / prim
    if not plug.exists():
        print(f'configsys: primary plugin "{prim}" is not synced — run `configsys plugin sync` first')
        return 1
    store = ctx.paths.user_dotfiles_dir
    entries = sorted(store.iterdir()) if store.exists() else []
    dfdir = plug / 'dotfiles'
    move = [e for e in entries if not (dfdir / e.name).exists() or args.force]
    skip = [e.name for e in entries if (dfdir / e.name).exists() and not args.force]
    sections = plugins.config_sections_text(ctx.paths.user_config_file, ('profiles', 'components'))

    gmoved_est, _gskip = _sweep_glue_to_primary(ctx, plug, dry_run=True, force=args.force)

    print(f'plugin init: merge local bits into primary "{prim}" ({plug})')
    print(f'  dotfiles    {len(move)} to move'
          + (f'; {len(skip)} already present (--force to overwrite): {", ".join(skip)}' if skip else ''))
    print(f'  glue        {gmoved_est} user snippet/override(s) to move')
    if sections:
        print(f'  config      your {", ".join(sections)} could move into the plugin (not auto-merged)')
    if args.dry_run or ctx.runner.pretend:
        print('\n(' + ('dry run' if args.dry_run else '--pretend') + ' — nothing written)')
        return 0
    if not move and not gmoved_est:
        print('\nnothing to merge.' + ('  (see the config note above.)' if sections else ''))
        return 0
    # author on a branch, not a detached HEAD — only now, right before the first write: a dry run
    # (or nothing to merge) must not move a tag-pinned primary (B17 / app-cli-07)
    plugins.ensure_branch(ctx.runner, plug)
    if move:
        primarygit.will_write(dfdir)
        dfdir.mkdir(parents=True, exist_ok=True)
        for e in move:
            dest = dfdir / e.name
            if dest.is_symlink() or dest.is_file():
                dest.unlink()
            elif dest.is_dir():
                shutil.rmtree(dest)
            shutil.move(str(e), str(dest))
        _repoint_dotfile_links(ctx, store, dfdir)        # live links follow the move (B9)
    gmoved, _ = _sweep_glue_to_primary(ctx, plug, dry_run=False, force=args.force)
    if gmoved:                                           # primary_glue_dir already set; repoint links
        _redeploy_user_glue(ctx)
    print(f'\nconfigsys: moved {len(move)} dotfile + {gmoved} glue item(s) into "{prim}". '
          'Push it to share.')
    return 0


def cmd_plugin_set_source(ctx, args, decls):
    '''Swap a declared plugin's `source:` (e.g. a local path -> github:you/name after you push),
    keeping its ref/primary flag. Then `plugin sync` fetches from the new source.'''
    from .. import plugins
    match = [d for d in decls if plugins.dir_name(d['source']) == args.name]
    if not match:
        print(f'configsys: no plugin named "{args.name}" in your config')
        return 1
    new_source = plugins.abs_local_source(args.source)   # a local path -> absolute (stable decl)
    if ctx.runner.pretend:
        print(f'configsys: [pretend] would set {args.name} source -> {new_source}')
        return 0
    for d in match:
        d['source'] = new_source
    plugins.set_declared(ctx.paths.user_config_file, decls)
    print(f'configsys: {args.name} source -> {new_source}  (run `configsys plugin sync` to fetch)')
    _retarget_clone(ctx, args.name, new_source)
    return 0


def _retarget_clone(ctx, old_dir, new_source):
    '''After `plugin set-source`, point the SYNCED clone at the new source too — sync only `git
    fetch`es an existing clone, so without this it would keep pulling the OLD remote. Sets (or adds)
    `origin` to the new clone URL via the runner. Leaves the dir alone when the new source isn't
    git-transported, is the clone itself (locally authored), or syncs into a different dir.'''
    from .. import plugins
    import shlex
    pdir = ctx.paths.plugins_dir / old_dir
    if not (pdir / '.git').exists():
        return
    if plugins.dir_name(new_source) != old_dir:
        print(f'configsys: note — {new_source} syncs into {plugins.dir_name(new_source)}/; the old '
              f'clone {pdir} is left in place (remove it by hand once the new one syncs)')
        return
    if not plugins.is_git_source(new_source):
        return                                         # a registered transport materializes it
    if plugins.is_local_authored(new_source, pdir):
        return                                         # the source IS this dir — nothing to fetch
    dq, uq = shlex.quote(str(pdir)), shlex.quote(plugins.clone_url(new_source))
    r = ctx.runner.run(f'git -C {dq} remote set-url origin {uq} 2>/dev/null || '
                       f'git -C {dq} remote add origin {uq}', capture=True)
    if r is not None and not r.ok:
        print(f'configsys: warning — could not point {pdir} at the new source; sync may still fetch '
              f'the old remote (fix: git -C {pdir} remote set-url origin {plugins.source_url(new_source)})',
              file=sys.stderr)
        return
    plugins.set_push_remote(ctx.runner, pdir, new_source)   # ssh push url for a github:/gitlab: source
    print(f'configsys: retargeted the synced clone\'s origin -> {plugins.source_url(new_source)}')


def cmd_plugin_diff(ctx, args, eff):
    '''`plugin diff NAME [--ref R]`: print the review diff — the TUI Plugins diff pane, as text.'''
    from .. import actions, plugins
    target = plugins.find_decl(eff, ctx.paths.plugins_dir, args.name)
    if target is None:
        print(f'configsys: no declared plugin matches {args.name!r}')
        return 1
    row = plugins.status(ctx.paths.plugins_dir, [target])[0]
    remote = args.to
    if not remote:
        remote, _kind = plugins.latest_ref(ctx.runner, target['source'])
    kind, base, to, what = actions.plugin_review_plan(row, remote)
    if kind is None:
        print(f'configsys: {row["name"]}: {what}')
        return 1
    if ctx.runner.pretend:
        print(f'configsys: [pretend] would fetch {to} to review {row["name"]} ({what})')
        return 0
    files, note, _plan = actions.plugin_review(ctx, target, row, remote)
    frm = '(nothing)' if base is None else (row['ref'] or 'HEAD') if base == 'HEAD' else base
    print(f'configsys: {row["name"]}: {frm} -> {to} — {what}')
    for f in files:
        print(f'diff --git a/{f["path"]} b/{f["path"]}')
        for _k, line in f['lines']:
            print(line)
    if not files:
        print(f'configsys: {note}')
    return 0 if files or not note or 'identical' in note or 'up to date' in note else 1


def _primary_dir_name(ctx):
    from .. import plugins
    try:
        return plugins.primary_name(plugins.declared(ctx.paths.user_config_file))
    except Exception:                                  # noqa: BLE001 — an unreadable config: no primary
        return None


def _print_sync(ctx, results):
    '''Print plugin sync outcomes, one per line, then a plain sentence for any that need one
    (local changes kept, diverged from the remote, commits not pushed — plugins.sync_note).'''
    from .. import plugins
    notes = []
    prim = _primary_dir_name(ctx)
    for name, action in results:
        print(f'  {action:8} {name}')
        note = plugins.sync_note(name, action, ctx.paths.plugins_dir, primary=name == prim)
        if note:
            notes.append(note)
    for note in notes:
        print(f'configsys: {note}')


class _CliPushUI:
    '''`plugin push`'s questions (`primarygit.Question`), asked on the terminal: the title, what it
    lists, then its choices as `[k] label`. Not a terminal: the question's unattended answer.
    `include` (--include-edits) answers include-own yes; `yes` (--yes) answers confirm-push yes.'''

    def __init__(self, include=False, yes=False):
        self.interactive = sys.stdin.isatty() and sys.stdout.isatty()
        self.include, self.yes = include, yes

    def ask(self, q):
        if q.kind == 'confirm-push' and (self.yes or not self.interactive):
            return True                                # --yes, or a script: the command is consent
        print(f'configsys: {q.title}')
        for line in q.listing():
            print(f'    {line}')
        if q.kind == 'include-own' and self.include:
            return True
        if not self.interactive:
            return q.unattended
        prompt = '  ' + '  '.join(f'[{c.key}] {c.label}' for c in q.choices) + ': '
        try:
            key = input(prompt).strip().lower()[:1]
        except EOFError:
            return q.enter
        return q.answer(key)

    def edit(self, path):
        _edit_conflict(path)

    def progress(self, text):
        pass


def _plugin_log(ctx, args):
    '''`plugin log`: the primary's recent commits, newest first, marked ↑ (not pushed) and * (made by
    configsys — `plugin undo` takes back the newest of those).'''
    found = primarygit.history(ctx, max(1, args.n))
    if found is None:
        print('configsys: you have no synced primary plugin on a branch.')
        return 1
    name, changes = found
    print(f'{name}: the last {primarygit.count_phrase(len(changes), "commit")}   (↑ not pushed yet · * made by '
          f'configsys)')
    for c in changes:
        files = ', '.join(c.files[:6]) + (f' … +{len(c.files) - 6}' if len(c.files) > 6 else '')
        print(f'  {"↑" if not c.pushed else " "}{"*" if c.by_configsys else " "} {c.short} {c.date}  '
              f'{c.subject}' + (f'   [{files}]' if files else ''))
    last = primarygit.undoable(changes)
    if last:
        print(f'\n`configsys plugin undo` takes back {last.short} "{last.subject}".')
    return 0


def _plugin_undo(ctx, args):
    '''`plugin undo`: show the newest configsys change, ask on a terminal (unless --yes), take it back.'''
    def confirm(change):
        if args.yes or not (sys.stdin.isatty() and sys.stdout.isatty()):
            return True
        other = change.machine and change.machine != primarygit.machine_name(ctx)
        print(f'configsys: undo {change.short} "{change.subject}"'
              + ('' if change.pushed else '  (not pushed yet)') + f'  [{", ".join(change.files)}]'
              + (f'\n  NOTE: this change was made on {change.machine}, not this machine' if other else ''))
        print('  any file it ADDED leaves the primary (and your disk) — a copy is saved under '
              f'{ctx.paths.state_dir}/undo/{change.short}/ first')
        try:
            return input('Undo it? [y/N] ').strip().lower()[:1] == 'y'
        except EOFError:
            return False
    ok, lines = primarygit.undo(ctx, confirm)
    for line in lines:
        print(f'configsys: {line}')
    if ok and not ctx.runner.pretend:
        _after_primary_commit(ctx)                     # under `auto` a revert is pushed like any edit
    return 0 if ok else 1


def _edit_conflict(path):
    '''Open a file holding conflict markers in $VISUAL/$EDITOR (else nano, else vi), on the terminal.'''
    import shlex as _shlex
    import shutil
    import subprocess
    editor = (os.environ.get('VISUAL') or os.environ.get('EDITOR')
              or ('nano' if shutil.which('nano') else 'vi'))
    print(f'configsys: both versions are in {path}, between <<<<<<< and >>>>>>> lines. Keep what you '
          f'want, delete the marker lines, save, and quit the editor.')
    try:
        subprocess.run([*_shlex.split(editor), str(path)])
    except Exception as e:                               # noqa: BLE001 — markers stay; push stops
        print(f'configsys: could not open {editor}: {e}')


def cmd_plugin(ctx, args):
    from .. import actions, plugins, primarygit
    decls = plugins.declared(ctx.paths.user_config_file)   # top-config decls (for edits)
    # the full set incl. transitively-declared plugins (for read-only views + trust)
    eff = plugins.effective_declared(ctx.paths.user_config_file, ctx.paths.plugins_dir)
    sub = getattr(args, 'plugin_command', None) or 'list'

    if sub == 'sync':
        if not decls:
            print('configsys: no plugins declared (add one: `configsys plugin add <source>`)')
            return 0
        before = active_snapshot(ctx.config)
        _print_sync(ctx, actions.plugin_sync(ctx, decls))
        print_sync_delta(before, ctx.config)           # how the active set changed across the sync
        return 0

    if sub == 'init':
        return cmd_plugin_init(ctx, args, decls)

    if sub == 'set-source':
        return cmd_plugin_set_source(ctx, args, decls)

    if sub == 'bless':
        if args.source.lower() == 'none':
            return cmd_plugin(ctx, argparse.Namespace(plugin_command='unbless'))
        ok, msg, results = actions.plugin_bless(ctx, args.source)
        _print_sync(ctx, results)
        print(f'configsys: {msg}')
        return 0 if ok else 1

    if sub == 'unbless':
        _ok, msg = actions.plugin_unbless(ctx)
        print(f'configsys: {msg}')
        return 0

    if sub == 'add':
        ok, msg, results = actions.plugin_add(ctx, args.source, args.ref,
                                              local=getattr(args, 'local', False),
                                              pin=getattr(args, 'pin', False),
                                              replace=getattr(args, 'replace', False))
        _print_sync(ctx, results)
        if not ok:
            print(f'configsys: {msg}')
            return 1
        for line in msg.split('\n'):
            print(f'configsys: {line}')
        return 0

    if sub == 'remove':
        ok, msg = actions.plugin_remove(ctx, args.name, force=getattr(args, 'force', False))
        print(f'configsys: {msg}')
        if not ok:
            return 1
        if ' from ' in msg:                          # removed from a plugin's own file
            print('configsys: `configsys plugin push` shares the removal with your other machines')
        return 0

    if sub == 'update':
        before = active_snapshot(ctx.config)           # report how the active set changes across the update
        # No name means every plugin (like `sync`); --all is an explicit alias for the same.
        if getattr(args, 'all', False) or not args.name:
            if args.name:
                print('configsys: pass a plugin name OR --all, not both')
                return 1
            if args.ref:
                print('configsys: --ref updates a single plugin — drop it (with --latest) to update all')
                return 1
            rows = actions.plugin_update_all(ctx, latest=getattr(args, 'latest', False),
                                             pin=getattr(args, 'pin', False))
            if not rows:
                print('configsys: no plugins declared')
                return 0
            for _src, ok, msg in rows:
                print(f'  {"ok " if ok else "FAIL"}  {msg}')
            failed = [s for s, ok, _m in rows if not ok]
            print(f'configsys: updated {len(rows) - len(failed)}/{len(rows)} plugins'
                  + (f' ({len(failed)} failed)' if failed else ''))
            print_sync_delta(before, ctx.config)
            return 1 if failed else 0
        ok, msg, results = actions.plugin_update(ctx, args.name, args.ref,
                                                 pin=getattr(args, 'pin', False),
                                                 latest=getattr(args, 'latest', False))
        if not ok:
            print(f'configsys: {msg}')
            return 1
        _print_sync(ctx, results)
        print(f'configsys: {msg}')
        print_sync_delta(before, ctx.config)
        return 0

    if sub == 'trust':
        # A plugin needs trust if it ships code OR command-carrying recipes (script/source/glue);
        # both run only once its current content is approved. Thin skin over the shared action layer.
        from .. import actions
        if getattr(args, 'all', False) or not args.name:
            n, note = actions.plugin_trust_all(ctx)
            print(f'configsys: {note}')
            return 0
        ok, note = actions.plugin_trust(ctx, args.name)
        print(f'configsys: {note}')
        # "nothing to trust" (an inert data plugin) is a benign no-op, not an error (exit 0).
        return 0 if (ok or 'nothing to trust' in note) else 1

    if sub == 'untrust':
        _ok, note = actions.plugin_untrust(ctx, args.name)
        print(f'configsys: {note}')
        return 0

    if sub in ('lock', 'unlock'):
        ok, note = (actions.plugin_lock if sub == 'lock' else actions.plugin_unlock)(ctx, args.name)
        print(f'configsys: {note}')
        return 0 if ok else 1

    if sub == 'diff':
        return cmd_plugin_diff(ctx, args, eff)

    if sub == 'push':
        ok, lines = primarygit.push(ctx, _CliPushUI(include=getattr(args, 'include_edits', False),
                                                    yes=getattr(args, 'yes', False)))
        for line in lines:
            print(f'configsys: {line}')
        return 0 if ok else 1

    if sub == 'log':
        return _plugin_log(ctx, args)

    if sub == 'undo':
        return _plugin_undo(ctx, args)

    if sub == 'list':
        rows = plugins.status(ctx.paths.plugins_dir, eff,
                              trust_file=ctx.paths.plugin_trust_file,
                              lock_file=ctx.paths.plugin_lock_file)
        if not rows:
            print('configsys: no plugins declared')
            return 0
        top = {plugins.dir_name(d['source']) for d in decls}
        for r in rows:
            if not r['synced']:
                state = 'not synced (run: configsys plugin sync)'
            elif r['checksum'] == 'mismatch':
                state = 'CHECKSUM MISMATCH — quarantined (content != declared sha256; re-pin or re-sync)'
            elif not r['abi_ok']:
                state = f'incompatible (needs plugin ABI {r["requires_abi"]})'
            else:
                state = 'ok'
                if r.get('local'):
                    state += '  [local — unpushed; push, then `configsys plugin set-source`]'
                cs = r['code_state']
                # word it by what actually needs trust: a code: module, command-carrying recipes
                # (via:script/source/glue), or both.
                what = ('code + recipes' if r.get('has_code') and r.get('has_recipes')
                        else 'code' if r.get('has_code') else 'recipes')
                if cs == 'trusted':
                    state += f'  [{what} trusted]'
                elif cs == 'untrusted':
                    state += f'  [ships {what} — untrusted; run: configsys plugin trust {r["name"]}]'
                elif cs == 'changed':
                    state += (f'  [{what} changed since trust — re-approve: '
                              f'configsys plugin trust {r["name"]}]')
            ref = f' @{r["ref"]}' if r['ref'] else ''
            tags = ('  [primary]' if r['primary'] else
                    ('  [via primary]' if plugins.dir_name(r['source']) not in top else ''))
            if r.get('locked'):
                state += f'  [locked since {r["locked"]} — no sync/update/trust; configsys plugin unlock {r["name"]}]'
            if r['primary'] and r['synced']:
                if getattr(args, 'fetch', False) and not primarygit.fetch(ctx):
                    state += '  [could not fetch its remote — counts are as of the last fetch]'
                where = primarygit.describe(primarygit.state(ctx))
                if where:
                    state += f'  [{where}]'
            print(f'  {r["name"]:22} {r["source"]}{ref}{tags}')
            print(f'  {"":22} {state}')
            if r.get('provisions'):
                print(f'  {"":22} provides: {", ".join(r["provisions"])}')
        for kind, name, dirs in plugins.declared_conflicts(ctx.paths.plugins_dir, eff):
            print(f'  {_fmt_conflict(kind, name, dirs)}')
        for drv, key in plugins.shadowed_builtins(ctx.paths.plugins_dir, eff):
            print(f'  {plugins.fmt_shadow(drv, key)}')
        return 0

    print(f'configsys: unknown plugin subcommand {sub!r}')
    return 2


def _after_primary_commit(ctx):
    '''A CLI command just committed to the primary: under `primary-push: auto` push it (a failure is
    one line, retried next time); under `ask` / `auto-on-quit` (which pushes only when you quit the
    TUI) say it isn't pushed yet; under `manual` stay quiet (`primarygit.PUSH_POLICY`).'''
    then = primarygit.PUSH_POLICY[primarygit.push_mode(ctx)]['after_cli']
    if then == 'push':
        ok, lines = primarygit.push(ctx)               # no questions: your own edits stay out
        if lines:
            print(f'configsys: {lines[-1] if ok else "not pushed automatically — " + lines[-1]}')
    elif then == 'hint':
        st = primarygit.state(ctx)
        if st and st.ahead:
            print(f'configsys: saved to {st.name} — {primarygit.count_phrase(st.ahead)} not pushed '
                  f'yet; `configsys plugin push` shares {primarygit.them_phrase(st.ahead)}.')
