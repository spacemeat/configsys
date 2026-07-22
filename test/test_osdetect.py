from configsys import osdetect


def _write(tmp_path, text):
    p = tmp_path / 'os-release'
    p.write_text(text)
    return str(p)


def test_pop_maps_to_pop_os_block(tmp_path):
    path = _write(tmp_path, 'ID=pop\nID_LIKE="ubuntu debian"\nVERSION_CODENAME=jammy\n')
    info = osdetect.detect(env={}, os_release_path=path)
    assert info.id == 'pop'
    assert info.block == 'pop_os!'
    assert info.id_like == ['ubuntu', 'debian']


def test_ubuntu_maps_to_itself(tmp_path):
    path = _write(tmp_path, 'ID=ubuntu\nID_LIKE=debian\n')
    info = osdetect.detect(env={}, os_release_path=path)
    assert info.block == 'ubuntu'
    assert info.id_like == ['debian']


def test_debian_no_id_like(tmp_path):
    path = _write(tmp_path, 'ID=debian\n')
    info = osdetect.detect(env={}, os_release_path=path)
    assert info.block == 'debian'
    assert info.id_like == []


def test_env_override_wins(tmp_path):
    path = _write(tmp_path, 'ID=ubuntu\n')
    info = osdetect.detect(env={'CONFIGSYS_OS': 'pop'}, os_release_path=path)
    assert info.block == 'pop_os!'


def test_missing_file_is_empty():
    info = osdetect.detect(env={}, os_release_path='/nonexistent/os-release')
    assert info.id == ''
    assert info.block == ''


def test_quotes_and_comments_ignored(tmp_path):
    path = _write(tmp_path, '# a comment\nID="ubuntu"\n\nPRETTY_NAME="Ubuntu 22.04"\n')
    info = osdetect.detect(env={}, os_release_path=path)
    assert info.block == 'ubuntu'


def test_rebuilds_now_map_to_their_own_block(tmp_path):
    # rocky/almalinux/centos/manjaro used to alias to rhel/arch; each now has its own routes
    # block (using: rhel / arch), so detection returns the ID unchanged — identity + display.
    for id in ('rocky', 'almalinux', 'centos', 'manjaro', 'endeavouros', 'linuxmint'):
        info = osdetect.detect(env={}, os_release_path=_write(tmp_path, f'ID={id}\n'))
        assert info.block == id


def test_opensuse_hyphenated_ids_alias_to_underscore_blocks(tmp_path):
    # the `when:` DSL has no hyphen, so the blocks use `_`; os-release's hyphenated IDs alias in.
    leap = osdetect.detect(env={}, os_release_path=_write(tmp_path, 'ID=opensuse-leap\nVERSION_ID=15.6\n'))
    assert leap.block == 'opensuse_leap' and leap.version == '15.6'
    tw = osdetect.detect(env={}, os_release_path=_write(tmp_path, 'ID=opensuse-tumbleweed\n'))
    assert tw.block == 'opensuse_tumbleweed'


def test_steamos_still_borrows_arch(tmp_path):
    # SteamOS (Holo) has no block of its own, so it keeps its arch alias.
    info = osdetect.detect(env={}, os_release_path=_write(tmp_path, 'ID=steamos\n'))
    assert info.block == 'arch'


# --- Fedora Atomic / uBlue detection ---------------------------------------

def _marker(tmp_path):
    m = tmp_path / 'ostree-booted'
    m.write_text('')
    return str(m)


def test_silverblue_variant_folds_to_atomic(tmp_path):
    path = _write(tmp_path, 'ID=fedora\nVARIANT_ID=silverblue\nVERSION_ID=40\n')
    info = osdetect.detect(env={}, os_release_path=path, ostree_marker='/nonexistent')
    assert info.id == 'fedora'            # real id kept for display / when: atoms
    assert info.block == 'fedora_atomic'  # but routed as the atomic environment
    assert info.version == '40'


def test_kinoite_variant_folds_to_atomic(tmp_path):
    path = _write(tmp_path, 'ID=fedora\nVARIANT_ID=kinoite\nVERSION_ID=41\n')
    info = osdetect.detect(env={}, os_release_path=path, ostree_marker='/nonexistent')
    assert info.block == 'fedora_atomic'


def test_ublue_with_fedora_variant_caught_by_ostree_marker(tmp_path):
    # Bazzite/Bluefin can report VARIANT_ID=fedora (ublue-os/bazzite#1249); the ostree
    # marker is the robust catch-all.
    path = _write(tmp_path, 'ID=fedora\nVARIANT_ID=fedora\nVERSION_ID=40\n')
    info = osdetect.detect(env={}, os_release_path=path, ostree_marker=_marker(tmp_path))
    assert info.block == 'fedora_atomic'


def test_plain_fedora_is_not_atomic(tmp_path):
    path = _write(tmp_path, 'ID=fedora\nVARIANT_ID=workstation\nVERSION_ID=41\n')
    info = osdetect.detect(env={}, os_release_path=path, ostree_marker='/nonexistent')
    assert info.block == 'fedora'


def test_forced_os_bypasses_atomic_remap(tmp_path):
    # --os fedora means the user explicitly wants mutable fedora, even on an ostree box
    path = _write(tmp_path, 'ID=fedora\nVARIANT_ID=silverblue\n')
    info = osdetect.detect(env={'CONFIGSYS_OS': 'fedora'}, os_release_path=path,
                           ostree_marker=_marker(tmp_path))
    assert info.block == 'fedora'
    # and forcing the atomic block directly works
    assert osdetect.detect(env={'CONFIGSYS_OS': 'fedora_atomic'}).block == 'fedora_atomic'


def test_non_fedora_ostree_distro_not_folded(tmp_path):
    # the atomic fold is fedora-family-gated: another ostree distro keeps its own identity
    path = _write(tmp_path, 'ID=endless\n')
    info = osdetect.detect(env={}, os_release_path=path, ostree_marker=_marker(tmp_path))
    assert info.block == 'endless'
