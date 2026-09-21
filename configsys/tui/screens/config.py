'''config.py — the Config (machine settings) screen as a Screen (build_vm/draw/handle).

Migrated off the monolithic menu.py painter (docs/d2-mvvm-plan.md), mirroring the Plugins
pattern-setter. The model is the existing `menu.ConfigScreen` (the settings catalog + cursor/scroll),
composed unchanged; this adds the three MVVM seams:

- build_vm: computes the PURE per-setting content — name, value string, the (state text, role) of the
  `default` column, the (store name, suffix, role) of the `store` column, the word-wrapped description
  lines and the man ref — plus the status/nav strings and the has_primary flag. No curses, no panel
  geometry (the wrap width is the one size-derived input, and it follows from `size` alone).
- draw: lays the content out (panel rect, the vx/dx/ex column math, the keep-cursor-in-view scroll
  written back to the model, scrollbar) and paints it. It reproduces menu._draw_config cell for cell,
  which test_screen_config pins against the legacy painter.
- handle: the former `if screen == 'config'` dispatch, returning an Intent (note / dirty / goto)
  instead of mutating loop-scope locals.
'''

import os

from .. import menu
from ..menu import (_DRIVER_ABBR, ConfigScreen as _ConfigModel, _draw_nav, _fill_bg, _fit,
                    _input_box, _order_list, _page_rows, _panel, _popup_choose, _put, _scrollbar_v,
                    _setting_str, _wordwrap)
from .base import Intent, Screen, ViewModel


class ConfigVM(ViewModel):
    '''Pure render content for one Config frame — settled by build_vm, painted by draw.'''

    def __init__(self):
        self.has_primary = False
        self.title = 'machine settings  ·  your values here override the built-in defaults'
        # per-setting content, one entry per model key (scroll-independent)
        self.names = []            # setting key
        self.values = []           # value column string
        self.states = []           # (text, role) for the `default` column
        self.stores = []           # (name, suffix, role) for the `store` column
        self.descs = []            # list[str] — wrapped description lines
        self.mans = []             # 'man: <ref>' line
        # chrome
        self.status = ''
        self.note = ''             # transient action note (host-supplied)
        self.nav = ''


def _nav_str():
    km = menu._KEYMAP
    if km is not None:
        g = lambda a: km.glyph('config', a)
        return (f" {g('down')}/{g('up')} move · {g('confirm')} edit · {g('move')} local↔primary · "
                f"{g('theme')} theme · {g('quit')} quit ")
    return ' j/k move · enter/space edit · m local↔primary · t theme · q quit '


def _state(info):
    '''(text, role) for the `default` column — is this the built-in default, a config override,
    or an env override (which supersedes config)?'''
    if isinstance(info.get('source'), str) and info['source'].startswith('env '):
        return 'env', 'outdated'                      # amber: an environment override wins
    if info.get('home') in ('local', 'primary'):
        return 'custom', 'installed'                  # green: you've set it
    return 'default', 'info_dim'                      # dim: the built-in default


def _store(info, has_primary, local_path):
    '''(name, suffix, role) for the `store` column — the NORMALIZED location the value lives /
    edits land: "<plugin> (primary plugin)" or "<~-path> (machine-local)". The suffix always shows
    (the name truncates first). A location that differs from this setting's NATURE-DEFAULT store —
    a moved setting, or an env override that supersedes config — is highlighted; otherwise dimmed.'''
    nature = info.get('nature', 'uniform')
    default_type = 'primary' if (nature == 'uniform' and has_primary) else 'local'
    src = info.get('source')
    if isinstance(src, str) and src.startswith('env '):
        return src[4:], '(env override)', 'header'   # env supersedes config -> non-default store
    home, tgt = info.get('home'), info.get('target')
    if home == 'primary' or (home is None and tgt and tgt != 'top config'):
        pname = info.get('home_label') if home == 'primary' else tgt
        name, suffix, loc_type = pname, '(primary plugin)', 'primary'
    else:
        name, suffix, loc_type = local_path, '(machine-local)', 'local'
    return name, suffix, ('header' if loc_type != default_type else 'scope')   # header = relocated


class ConfigScreen(Screen):
    id = 'config'

    def __init__(self, ctx, model=None):
        self.ctx = ctx
        self.model = model if model is not None else _ConfigModel(ctx)

    def reload(self):
        self.model.reload()

    # -- build_vm ---------------------------------------------------------

    def build_vm(self, ctx, size):
        from ... import actions
        from ... import plugins as _pl
        cs = self.model
        vm = ConfigVM()
        h, w = size
        iw = w - 2                                    # panel interior width (panel spans the row)
        vm.has_primary = bool(_pl.primary_name(_pl.declared(ctx.paths.user_config_file)))
        _home = os.path.expanduser('~')
        p = str(ctx.paths.user_config_file)
        local_path = '~' + p[len(_home):] if _home and p.startswith(_home) else p
        for key in cs.keys:
            info = cs.settings[key]
            vm.names.append(key)
            vm.values.append(_setting_str(info['kind'], info['value'], key))
            vm.states.append(_state(info))
            vm.stores.append(_store(info, vm.has_primary, local_path))
            vm.descs.append(_wordwrap(info['desc'], iw - 4))
            vm.mans.append(f'man: {info["man"]}')
        cur_key = cs.keys[cs.cur] if cs.keys else None
        tgt = cs.settings.get(cur_key, {}).get('target') if cur_key else None
        vm.status = f' {cur_key}: edits → {tgt}' if tgt else f' edits → {actions.edit_target(ctx)[1]}'
        vm.nav = _nav_str()
        return vm

    # -- draw -------------------------------------------------------------

    def draw(self, surface, pal, vm):
        cs = self.model
        surface.erase()
        h, w = surface.getmaxyx()
        pal.use_page('config')
        if pal.gradient:
            _fill_bg(surface, pal, h, w)
        _draw_nav(surface, pal, 'config', h, w)
        it, il, ih, iw = _panel(surface, pal, 1, 0, h - 3, w, vm.title, True, h, w)

        # aligned columns (lowercase headers, like the Plugins table); the description + man ref wrap
        # on the rows below each setting. Column x-offsets are relative to the panel interior `il`.
        # `store` takes the remainder (it holds a path, so it wants the room); `value` got +3 for
        # driver-preference.
        nx, vx = 0, min(18, iw // 4)
        dx = min(vx + 27, iw - 24)
        ex = min(dx + 9, iw - 15)
        nw, vw, dw = vx - 1, dx - vx - 1, ex - dx - 1
        ew = max(6, iw - ex - 1)

        def col(y, cx, text, cw, role, sel):
            if 0 <= cx < iw - 1:
                _put(surface, y, il + cx, _fit(text, min(cw, iw - cx - 1)),
                     pal.style(role, y, il + cx, h, w, selected=sel))

        def col_store(y, cx, name, suffix, cw, role, sel):
            '''Draw the store cell, keeping the (suffix) visible — the descriptor matters more than
            the long path, so the name truncates first.'''
            if len(name) + 1 + len(suffix) <= cw or cw <= len(suffix) + 4:
                txt = _fit(f'{name} {suffix}', cw)
            else:
                txt = f'{_fit(name, cw - len(suffix) - 1)} {suffix}'
            col(y, cx, txt, cw, role, sel)

        def block_h(i):
            return 1 + len(vm.descs[i]) + 1 + 1           # cols + desc + man + gap row

        avail = ih - 1                                    # header row consumes one
        if cs.cur < cs.top:
            cs.top = cs.cur
        while cs.top < cs.cur and sum(block_h(i) for i in range(cs.top, cs.cur + 1)) > avail:
            cs.top += 1                                   # keep the cursor's block in view

        # header row (lowercase column names)
        for cx, cw, label in ((nx, nw, 'name'), (vx, vw, 'value'), (dx, dw, 'default'),
                              (ex, ew, 'store')):
            col(it, cx, label, cw, 'menu_header', False)

        y, shown = it + 1, 0
        for i in range(cs.top, len(cs.keys)):
            bh = block_h(i)
            if y + bh - 1 > it + ih:                      # the whole block wouldn't fit
                break
            sel = i == cs.cur
            if sel:
                _put(surface, y, il, ' ' * iw, pal.fill(y, il, h, w, selected=True))
            st_txt, st_role = vm.states[i]
            s_name, s_suffix, s_role = vm.stores[i]
            col(y, nx, vm.names[i], nw, 'label' if sel else 'component', sel)
            col(y, vx, vm.values[i], vw, 'scope_choice', sel)
            col(y, dx, st_txt, dw, st_role, sel)
            col_store(y, ex, s_name, s_suffix, ew, s_role, sel)
            dy = y + 1
            for line in vm.descs[i]:                      # word-wrapped description, not cut off
                _put(surface, dy, il + 3, _fit(line, iw - 4), pal.style('info_dim', dy, il, h, w))
                dy += 1
            _put(surface, dy, il + 3, _fit(vm.mans[i], iw - 4),  # man ref — its own colour
                 pal.style('method_dim', dy, il, h, w))
            y += bh
            shown += 1
        _scrollbar_v(surface, pal, it + 1, il + iw, ih - 1, cs.top, max(1, shown), len(cs.keys), h, w)
        _put(surface, h - 2, 0, _fit(vm.status + (f'    {vm.note}' if vm.note else ''), w),
             pal.style('status_line', h - 2, 0, h, w))
        _put(surface, h - 1, 0, _fit(vm.nav.ljust(w), w), pal.style('footer', h - 1, 0, h, w))
        surface.refresh()

    # -- handle -----------------------------------------------------------

    def handle(self, ch, ctx, stdscr, pal):
        '''One key. Mutates the model, runs the edit modals, returns an Intent(note, dirty, goto).
        Ported verbatim from the former config dispatch: `theme` -> goto='theme'; move / bool / scope /
        driver-preference / dir / other-list edits mark the tree dirty; splash / effects / scalar
        edits deliberately do not.'''
        from ... import actions
        cs = self.model
        km = menu._KEYMAP
        cact = km.action_for('config', ch) if km is not None else None
        note = None
        dirty = False
        goto = None
        if cact == 'down':
            cs.cur = min(len(cs.keys) - 1, cs.cur + 1)
        elif cact == 'up':
            cs.cur = max(0, cs.cur - 1)
        elif cact == 'page-down':
            cs.cur = min(len(cs.keys) - 1, cs.cur + _page_rows(stdscr))
        elif cact == 'page-up':
            cs.cur = max(0, cs.cur - _page_rows(stdscr))
        elif cact == 'top':
            cs.cur = 0
        elif cact == 'bottom':
            cs.cur = max(0, len(cs.keys) - 1)
        elif cact == 'theme':
            goto = 'theme'
        elif cact == 'move':                    # move this setting local <-> primary
            key = cs.keys[cs.cur]
            try:
                ok, msg = actions.move_config_setting(ctx, key)
                note = msg
                if ok:
                    cs.reload()
                    dirty = True
            except Exception as e:  # noqa: BLE001 — surface, don't crash
                note = f'move failed: {e}'
        elif cact in ('confirm', 'select'):
            key = cs.keys[cs.cur]
            info = cs.settings[key]
            try:
                if info['kind'] == 'bool':
                    actions.set_config_setting(
                        ctx, key, ['false' if info['value'] else 'true'])
                    note = f'{key} = {"false" if info["value"] else "true"}'
                    cs.reload()
                    dirty = True
                elif key == 'scope':                # scope: user (default) / system / unset
                    cur_idx = {'user': 0, 'system': 1}.get(info['value'], 2)
                    idx = _popup_choose(stdscr, pal, key,
                                        [('user', '(default)'), ('system', ''),
                                         ('unset', '(→ user)')], cur_idx)
                    if idx is not None:
                        actions.set_config_setting(ctx, key, [['user'], ['system'], []][idx])
                        note = f'{key} set'
                        cs.reload()
                        dirty = True
                elif key == 'splash':               # off / built-in / a plugin provider
                    from ...splashes import splash_names, _BUILTIN_SPLASH_NAMES
                    from ..splash import DEFAULT_SPLASH
                    from ... import plugins as _pl
                    _decls = _pl.effective_declared(ctx.paths.user_config_file, ctx.paths.plugins_dir)
                    prov2plug = _pl.splash_plugins(ctx.paths.plugins_dir, _decls)

                    def _tag(n):                    # show WHICH plugin provides a splash
                        return ('(built-in)' if n in _BUILTIN_SPLASH_NAMES
                                else prov2plug.get(n, '(plugin)'))
                    opts = ([('off', '(no animation)'), ('random', '(any installed splash)')]
                            + [(n, _tag(n)) for n in splash_names()])
                    names = [o[0] for o in opts]
                    cur = info['value']
                    cur = (_pl.resolve_splash_value(cur, ctx.paths.plugins_dir, _decls)
                           if isinstance(cur, str) else cur)
                    cur_idx = (0 if isinstance(cur, str) and cur.lower() in ('off', 'false', 'no')
                               else names.index(cur) if cur in names
                               else names.index(DEFAULT_SPLASH) if cur in (None, 'default')
                               and DEFAULT_SPLASH in names else 0)
                    idx = _popup_choose(stdscr, pal, key, opts, cur_idx)
                    if idx is not None:
                        val = names[idx]
                        # picking the built-in default clears the setting (tracks the default)
                        actions.set_config_setting(ctx, key, [] if val == DEFAULT_SPLASH else [val])
                        note = f'{key} = {val}'
                        cs.reload()
                elif key == 'effects':              # motion level: auto (unset) / full / reduced / none
                    opts = [('auto', '(SSH → reduced, else full)'), ('full', '(gradient + splash)'),
                            ('reduced', '(no gradient; calmer splash)'), ('none', '(no gradient/splash)')]
                    names = [o[0] for o in opts]
                    cur = info['value']             # 'full' | 'reduced' | 'none' | None (auto)
                    cur_idx = names.index(cur) if cur in names else 0
                    idx = _popup_choose(stdscr, pal, key, opts, cur_idx)
                    if idx is not None:
                        val = names[idx]
                        actions.set_config_setting(ctx, key, [] if val == 'auto' else [val])
                        note = f'{key} = {val}'
                        cs.reload()
                elif info['kind'] == 'scalar':      # any other scalar -> text input
                    new = _input_box(stdscr, pal, f'{key}  (empty clears)',
                                     str(info['value'] or ''))
                    if new is not None:
                        v = new.strip()
                        actions.set_config_setting(ctx, key, [v] if v else [])
                        note = f'{key} {"set" if v else "cleared"}'
                        cs.reload()
                elif key == 'driver-preference':    # ordered list -> reorder editor
                    from ...resolve import DEFAULT_DRIVER_PREFERENCE
                    cur = info['value'] or list(DEFAULT_DRIVER_PREFERENCE)
                    new = _order_list(stdscr, pal,
                                      'driver-preference — space grab, j/k move', cur,
                                      label=lambda d: f'{_DRIVER_ABBR.get(d, d) + ":":<5}{d}')
                    if new is not None:
                        actions.set_config_setting(ctx, key, new)
                        note = f'{key} reordered'
                        cs.reload()
                        dirty = True
                elif info['kind'] == 'dir':         # an install-layout path -> text input
                    new = _input_box(stdscr, pal, f'{key}  (path; empty = default/env)',
                                     str(info['value'] or ''))
                    if new is not None:
                        v = new.strip()
                        actions.set_config_setting(ctx, key, [v] if v else [])
                        note = f'{key} {"set" if v else "cleared"}'
                        cs.reload()
                        dirty = True
                else:                               # other list settings: input box
                    new = _input_box(stdscr, pal,
                                     f'{key}  (space-separated; empty clears)',
                                     ' '.join(info['value'] or []))
                    if new is not None:
                        actions.set_config_setting(ctx, key, new.split())
                        note = f'{key} set'
                        cs.reload()
                        dirty = True
            except Exception as e:  # noqa: BLE001 — surface, don't crash
                note = f'edit failed: {e}'
        return Intent(note=note, dirty=dirty, goto=goto)
