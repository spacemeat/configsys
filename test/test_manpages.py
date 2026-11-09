'''The checked-in man pages must stay in sync with their sources (the argparse parser and
docs/config-format.md). Regenerate with `python3 tools/gen_manpages.py` when this fails.'''

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_manpages_are_up_to_date():
    r = subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'gen_manpages.py'), '--check'],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr or r.stdout


def test_manpages_exist_and_have_headers():
    for rel, header in (('man/configsys.1', '.TH CONFIGSYS 1'),
                        ('man/configsys.hu.5', '.TH CONFIGSYS.HU 5')):
        with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
            first = f.readline()
        assert first.startswith(header), f'{rel}: {first!r}'


def _gen():
    import importlib.util
    spec = importlib.util.spec_from_file_location('gen_manpages', os.path.join(ROOT, 'tools', 'gen_manpages.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_files_lists_every_state_dir_location(tmp_path):
    # tests-tools-18: FILES is generated from gen_manpages.FILES, and that table can't fall behind Paths
    from pathlib import Path
    from configsys.paths import Paths
    gm = _gen()
    listed = {rel for rel, _purpose in gm.FILES}
    p = Paths(env={'CONFIGSYS_HOME': str(tmp_path)})
    for attr, val in vars(p).items():
        if not isinstance(val, Path) or val == p.state_dir or p.state_dir not in val.parents:
            continue
        rel = val.relative_to(p.state_dir).as_posix() + ('/' if attr.endswith('_dir') else '')
        assert rel in listed, f'Paths.{attr} ({rel}) is not in gen_manpages.FILES'
    with open(os.path.join(ROOT, 'man', 'configsys.1'), encoding='utf-8') as f:
        page = f.read()
    for rel in listed:
        assert f'\\fB{gm.STATE}/{rel}\\fR' in page


def test_inline_escapes_troff_control_characters():
    gm = _gen()
    assert gm._inline('.hidden is a request') == '\\&.hidden is a request'   # a leading . or '
    assert gm._inline("'quoted") == "\\&'quoted"                             # is a control line
    assert gm._inline('mid. sentence') == 'mid. sentence'
    assert gm._inline('a \\ backslash') == 'a \\e backslash'                 # \ is troff's escape
    assert gm._inline('`--pretend` and **bold** *it*') == '\\fB--pretend\\fR and \\fBbold\\fR \\fIit\\fR'
    assert gm._inline('per-machine [docs](x.md)') == 'per-machine docs'      # prose hyphens stay hyphens
    assert gm._code('.nf inside code') == '\\&.nf inside code'
