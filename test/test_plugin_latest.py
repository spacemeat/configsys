'''`plugin update --latest` ref resolution: pick the newest STABLE semver tag from the remote via
`git ls-remote`, else fall back to main (or master). Read-only, non-interactive.'''

from configsys import plugins
from configsys.runner import Result


class _LsRemoteRunner:
    '''Fakes `git ls-remote` for tags/heads from canned ref lists; every other call is ok/empty.'''
    def __init__(self, tags=(), heads=(), fail=False):
        self.tags, self.heads, self.fail = list(tags), list(heads), fail
        self.calls = []

    def run(self, cmd, *, sudo=False, capture=True, tui_active=None, cwd=None, env=None):
        self.calls.append(cmd)
        if self.fail:
            return Result(cmd, 128, stderr='fatal: could not read from remote')
        if 'ls-remote --tags' in cmd:
            body = '\n'.join(f'deadbeef\trefs/tags/{t}' for t in self.tags)
            return Result(cmd, 0, stdout=body)
        if 'ls-remote --heads' in cmd:
            body = '\n'.join(f'deadbeef\trefs/heads/{h}' for h in self.heads)
            return Result(cmd, 0, stdout=body)
        return Result(cmd, 0, stdout='')


def test_picks_highest_semver_tag():
    r = _LsRemoteRunner(tags=['v0.1.5', 'v0.1.10', 'v0.2.0', 'v0.1.9'])
    assert plugins.latest_ref(r, 'github:me/p') == ('v0.2.0', 'tag')


def test_numeric_ordering_not_lexical():
    # lexically 'v0.1.9' > 'v0.1.10'; numerically 0.1.10 wins
    r = _LsRemoteRunner(tags=['v0.1.9', 'v0.1.10'])
    assert plugins.latest_ref(r, 'github:me/p') == ('v0.1.10', 'tag')


def test_ignores_prerelease_and_junk_tags():
    r = _LsRemoteRunner(tags=['v1.0.0-rc1', 'nightly', 'v0.9.0', 'latest'], heads=['main'])
    assert plugins.latest_ref(r, 'github:me/p') == ('v0.9.0', 'tag')   # only the clean semver counts


def test_no_tags_falls_back_to_main():
    r = _LsRemoteRunner(tags=[], heads=['develop', 'main', 'master'])
    assert plugins.latest_ref(r, 'github:me/p') == ('main', 'branch')


def test_no_tags_no_main_falls_back_to_master():
    r = _LsRemoteRunner(tags=[], heads=['master', 'develop'])
    assert plugins.latest_ref(r, 'github:me/p') == ('master', 'branch')


def test_only_prerelease_tags_falls_back_to_branch():
    r = _LsRemoteRunner(tags=['v2.0.0-beta'], heads=['master'])
    assert plugins.latest_ref(r, 'github:me/p') == ('master', 'branch')


def test_unreachable_remote_returns_none():
    r = _LsRemoteRunner(fail=True)
    assert plugins.latest_ref(r, 'github:me/p') == (None, None)


def test_no_tags_no_known_branch_returns_none():
    r = _LsRemoteRunner(tags=[], heads=['develop', 'trunk'])
    assert plugins.latest_ref(r, 'github:me/p') == (None, None)


# -- plugin_update_all: the bulk "get 'em all to --latest" orchestration --------------------

def test_update_all_iterates_dedups_and_skips_local_authored(tmp_path, monkeypatch):
    import types

    from configsys import actions

    ctx = types.SimpleNamespace(paths=types.SimpleNamespace(
        user_config_file=str(tmp_path / 'configsys.hu'), plugins_dir=tmp_path / 'plugins'))

    # primary + two remotes + a duplicate of the first (dedup) + a locally-authored one
    monkeypatch.setattr(plugins, 'effective_declared', lambda *a: [
        {'source': 'github:me/primary'}, {'source': 'github:x/blender'},
        {'source': 'github:me/primary'},                 # dup -> collapsed
        {'source': str(tmp_path / 'plugins' / 'devplug')},   # local-authored -> skipped
    ])
    monkeypatch.setattr(plugins, 'is_local_authored',
                        lambda src, dest: 'devplug' in str(src))

    calls = []

    def fake_update(_ctx, src, *, pin=False, latest=False):
        calls.append((src, latest, pin))
        return True, f're-pinned {src} @v1.2.3 (latest tag)', []

    monkeypatch.setattr(actions, 'plugin_update', fake_update)

    rows = actions.plugin_update_all(ctx, latest=True, pin=True)

    updated = [src for src, _l, _p in calls]
    assert updated == ['github:me/primary', 'github:x/blender']       # deduped, local one not called
    assert all(latest and pin for _s, latest, pin in calls)           # flags threaded through
    assert len(rows) == 3                                             # 2 updated + 1 skipped (dup dropped)
    skipped = [m for s, ok, m in rows if 'skipped' in m]
    assert len(skipped) == 1 and 'devplug' in [s for s, _o, m in rows if 'skipped' in m][0]
