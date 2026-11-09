'''review-2026-11-2 D4 — the one link / unlink the config drivers share (drivers/_linked.py).'''

import os

from configsys.drivers import _linked
from configsys.runner import Runner


def _tree(tmp_path):
    store = tmp_path / 'store'
    store.mkdir()
    (store / 'a').write_text('ours')
    (store / 'b').write_text('ours too')
    other = tmp_path / 'other'
    other.mkdir()
    (other / 'x').write_text('theirs')
    return store, other, tmp_path / 'home' / 'dst'


def test_links_and_repoints_our_own_link(tmp_path):
    store, _other, dst = _tree(tmp_path)
    assert _linked.link(Runner(), store / 'a', dst, owned_roots=[store]).ok
    assert dst.is_symlink() and dst.read_text() == 'ours'
    assert _linked.link(Runner(), store / 'b', dst, owned_roots=[store]).ok   # ours: re-pointed
    assert dst.read_text() == 'ours too' and not list(dst.parent.glob('*.pre-configsys*'))


def test_already_in_place_is_a_noop(tmp_path):
    store, _other, dst = _tree(tmp_path)
    _linked.link(Runner(), store / 'a', dst, owned_roots=[store])
    before = os.readlink(dst)
    assert _linked.link(Runner(), store / 'a', dst, owned_roots=[store]).ok
    assert os.readlink(dst) == before


def test_a_real_file_and_another_tools_link_are_kept_aside(tmp_path):
    store, other, dst = _tree(tmp_path)
    dst.parent.mkdir(parents=True)
    dst.write_text('mine')
    res = _linked.link(Runner(), store / 'a', dst, owned_roots=[store])
    assert res.ok and 'moved your existing' in res.stdout
    assert dst.with_name('dst.pre-configsys').read_text() == 'mine'
    # now someone else's link (stow) sits there: it is NOT silently replaced either
    dst.unlink()
    dst.symlink_to(other / 'x')
    assert _linked.link(Runner(), store / 'a', dst, owned_roots=[store]).ok
    assert os.readlink(dst.with_name('dst.pre-configsys.1')) == str(other / 'x')
    assert dst.read_text() == 'ours'


def test_absorb_takes_a_real_file_when_free(tmp_path):
    store, _other, dst = _tree(tmp_path)
    dst.parent.mkdir(parents=True)
    dst.write_text('aliases')
    absorb = tmp_path / 'home' / 'conf.d' / 'pre-configsys-aliases.sh'
    assert _linked.link(Runner(), store / 'a', dst, owned_roots=[store], absorb=absorb).ok
    assert absorb.read_text() == 'aliases' and os.access(absorb, os.X_OK)
    # absorb taken -> a plain backup instead
    os.unlink(dst)
    dst.write_text('again')
    assert _linked.link(Runner(), store / 'a', dst, owned_roots=[store], absorb=absorb).ok
    assert dst.with_name('dst.pre-configsys').read_text() == 'again'


def test_unlink_removes_only_ours_and_restores_into_the_gap(tmp_path):
    store, other, dst = _tree(tmp_path)
    dst.parent.mkdir(parents=True)
    dst.write_text('mine')
    _linked.link(Runner(), store / 'a', dst, owned_roots=[store])
    assert _linked.unlink(Runner(), dst, owned_roots=[store]) == ('removed', dst.with_name('dst.pre-configsys'))
    assert not dst.is_symlink() and dst.read_text() == 'mine'
    assert _linked.unlink(Runner(), dst, owned_roots=[store])[0] == 'kept'     # a real file: yours
    dst.unlink()
    dst.symlink_to(other / 'x')
    assert _linked.unlink(Runner(), dst, owned_roots=[store])[0] == 'kept'     # another tool's link
    assert dst.is_symlink()
    dst.unlink()
    assert _linked.unlink(Runner(), dst, owned_roots=[store]) == ('absent', None)


def test_pretend_touches_nothing(tmp_path):
    store, _other, dst = _tree(tmp_path)
    dst.parent.mkdir(parents=True)
    dst.write_text('mine')
    msgs = []
    r = Runner(pretend=True, echo=msgs.append)
    assert _linked.link(r, store / 'a', dst, owned_roots=[store]).ok
    assert dst.read_text() == 'mine' and not dst.is_symlink()
    assert any('would move' in m for m in msgs) and any('would link' in m for m in msgs)
    os.unlink(dst)
    dst.symlink_to(store / 'a')
    assert _linked.unlink(r, dst, owned_roots=[store])[0] == 'removed'
    assert dst.is_symlink()                                    # still there


def test_one_shell_table_feeds_glue_and_the_guard():
    # D4: per-shell facts are one ShellSpec row each; glue's tables and the shell-writes guard derive
    from configsys import shellguard
    from configsys.drivers import glue
    from configsys.shells import SHELLS
    assert glue._GLUE_SHELLS == tuple(SHELLS)
    assert set(glue._INLINE_SHELLS) == {n for n, s in SHELLS.items() if s.mode == 'inline'}
    assert {n for _rel, n in shellguard.GUARDED} == set(SHELLS)       # every shell's rc is guarded
    assert ('.zshenv', 'zsh') in shellguard.GUARDED and ('.config/fish/conf.d', 'fish') in shellguard.GUARDED_DIRS
    for s in SHELLS.values():
        assert s.mode in ('native', 'rc-block', 'inline')
        assert (s.rc is None) == (s.mode == 'native')                  # only a native shell needs no rc
        assert s.confd.endswith('/conf.d')


def test_spec_states_are_named(tmp_path):
    from configsys.drivers._linked import SpecState
    st = SpecState('x', '~/x', 'linked', None, 'x', True, 'config')
    name, target, state, *_rest = st                                  # still unpacks
    assert (name, st.state, st.kind) == ('x', 'linked', 'config')
