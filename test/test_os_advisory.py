'''An os: block's `advisory:` (review-2026-11-2 app-cli-25): the OS caveats are data on the block,
inherited through `using:`, not Python prose keyed by block name — so a derivative gets them too.'''

from configsys.app import main
from configsys.routes import OsCascade


def _cascade():
    return OsCascade({
        'linux': {},
        'glibc_linux': {'using': 'linux'},
        'kde_linux': {'using': 'glibc_linux', 'advisory': 'KDE Linux detected —\n    no package\n manager'},
        'kde_spin': {'using': 'kde_linux'},
        'kde_own': {'using': 'kde_linux', 'advisory': 'its own caveat'},
        'kde_quiet': {'using': 'kde_linux', 'advisory': ''},
    })


def test_advisory_is_inherited_overridden_and_silenced():
    c = _cascade()
    assert c.advisory('kde_linux') == 'KDE Linux detected — no package manager'   # whitespace-normalized
    assert c.advisory('kde_spin') == 'KDE Linux detected — no package manager'    # via `using:`
    assert c.advisory('kde_own') == 'its own caveat'
    assert c.advisory('kde_quiet') is None
    assert c.advisory('glibc_linux') is None


def test_the_shipped_advisories_reach_the_diagnostics(tmp_path, capsys):
    for block, text in (('kde_linux', 'KDE Linux detected (alpha, immutable'),
                        ('chimera', 'Chimera Linux detected')):
        assert main(['--home', str(tmp_path), '--os', block, '--pretend', 'inspect']) == 0
        out = capsys.readouterr().out
        assert 'os-advisory' in out and text in out
    assert main(['--home', str(tmp_path), '--os', 'pop', '--pretend', 'inspect']) == 0
    assert 'os-advisory' not in capsys.readouterr().out


def test_a_derivative_block_inherits_the_advisory(tmp_path, capsys):
    cfg = tmp_path / '.config' / 'configsys'
    cfg.mkdir(parents=True)
    (cfg / 'configsys.hu').write_text('{ os: { kde_spin: { using: kde_linux } } }')
    assert main(['--home', str(tmp_path), '--os', 'kde_spin', '--pretend', 'inspect']) == 0
    assert 'KDE Linux detected' in capsys.readouterr().out
