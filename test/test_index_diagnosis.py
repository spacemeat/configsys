from configsys import app, failures

JENKINS_ERR = (
    "Reading package lists...\n"
    "W: GPG error: https://pkg.jenkins.io/debian-stable binary/ Release: The following "
    "signatures couldn't be verified because the public key is not available: "
    "NO_PUBKEY 7198F4B714ABFC68\n"
    "E: The repository 'https://pkg.jenkins.io/debian-stable binary/ Release' is not signed.")

JLIST = '/etc/apt/sources.list.d/jenkins.list'


def _finder(mapping):
    return lambda urls, dirs: mapping


def test_diagnose_names_cause_and_owned_component():
    owned = {JLIST: 'jenkins'}
    lines = app.diagnose_index_failure(
        JENKINS_ERR, 'apt', owned,
        finder=_finder({JLIST: 'https://pkg.jenkins.io/debian-stable'}))
    blob = '\n'.join(lines)
    assert f'Likely cause: {failures.SIGNATURE}' in blob
    assert '7198F4B714ABFC68' in blob                       # remediation carries the key id
    assert JLIST in blob and 'component `jenkins`' in blob   # attributed to the owning component


def test_diagnose_flags_foreign_source():
    lines = app.diagnose_index_failure(
        JENKINS_ERR, 'apt', {},                              # not in the owned map
        finder=_finder({'/etc/apt/sources.list.d/rando.list': 'https://pkg.jenkins.io/debian-stable'}))
    assert any('NOT managed by configsys' in ln for ln in lines)


def test_diagnose_reports_repo_when_file_not_found():
    lines = app.diagnose_index_failure(JENKINS_ERR, 'apt', {}, finder=_finder({}))
    assert any('pkg.jenkins.io' in ln for ln in lines)       # still names the repo


def test_diagnose_empty_on_unrecognised():
    assert app.diagnose_index_failure('everything is fine, actually', 'apt', {},
                                      finder=_finder({})) == []


def test_find_source_files_scans_injected_fs():
    files = {'/etc/apt/sources.list.d/jenkins.list': 'deb https://pkg.jenkins.io/debian-stable binary/',
             '/etc/apt/sources.list.d/other.list': 'deb https://deb.debian.org/debian stable main'}
    found = app._find_source_files(
        ['https://pkg.jenkins.io/debian-stable'], ('/etc/apt/sources.list.d',),
        exists=lambda p: True,
        listdir=lambda d: ['jenkins.list', 'other.list'],
        read=lambda p: files[p])
    assert found == {'/etc/apt/sources.list.d/jenkins.list': 'https://pkg.jenkins.io/debian-stable'}
