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
