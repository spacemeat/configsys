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
