'''The podman harness scripts' argument handling, with a stub `podman` that only logs its argv (the
real harnesses are gated, slow and networked — this checks what they WOULD run).'''

import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _podman_calls(tmp_path, script, *args):
    stub = tmp_path / 'bin'
    stub.mkdir()
    log = tmp_path / 'log'
    (stub / 'podman').write_text(f'#!/bin/sh\necho "$*" >> {log}\n')
    (stub / 'podman').chmod(0o755)
    subprocess.run(['bash', str(HERE / script), *args], check=True, capture_output=True,
                   env={'PATH': f'{stub}:/usr/bin:/bin'})
    return log.read_text().splitlines()


def test_fedora_toolchain_default_loops_over_each_release(tmp_path):
    # "${@:-43 44 45}" was ONE word with no args -> the tag `configsys-test:fedora43 44 45`
    builds = [c for c in _podman_calls(tmp_path, 'run-fedora-toolchain-in-podman.sh') if c.startswith('build')]
    assert [b.split()[3] for b in builds] == ['configsys-test:fedora43', 'configsys-test:fedora44',
                                              'configsys-test:fedora45']


def test_fedora_toolchain_named_releases_only(tmp_path):
    builds = [c for c in _podman_calls(tmp_path, 'run-fedora-toolchain-in-podman.sh', '44') if c.startswith('build')]
    assert [b.split()[3] for b in builds] == ['configsys-test:fedora44']
