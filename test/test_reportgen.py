from configsys import reportgen
from configsys.paths import Paths


def test_scrub_masks_tokens_labels_and_home():
    home = '/home/alice'
    text = ('cloning with GITHUB_TOKEN=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345\n'
            'password: hunter2 in /home/alice/.cache/x')
    out = reportgen.scrub(text, home=home, secrets=['hunter2'])
    assert 'ghp_ABCDEF' not in out                  # token shape redacted
    assert 'hunter2' not in out                      # known secret value redacted
    assert 'password: ***' in out                    # labeled value masked
    assert '~/.cache/x' in out and '/home/alice' not in out   # home collapsed


def test_secret_values_picks_secret_named_vars():
    env = {'GITHUB_TOKEN': 'abcd1234', 'MY_API_KEY': 'zzzz', 'PATH': '/usr/bin', 'HOME': '/h'}
    vals = reportgen.secret_values(env)
    assert 'abcd1234' in vals and 'zzzz' in vals
    assert '/usr/bin' not in vals and '/h' not in vals   # non-secret names ignored


def test_save_load_failure_roundtrip(tmp_path):
    paths = Paths(env={'CONFIGSYS_HOME': str(tmp_path)})
    rec = {'component': 'blender', 'unit': 'blender-build\\blender', 'driver': 'blender-build',
           'op': 'install', 'command': 'bash build.sh', 'exit': 2,
           'output': 'line one\nerror: boom\n', 'at': '2026-07-23 00:00:00'}
    reportgen.save_failure(paths, rec)
    got = reportgen.load_failure(paths)
    assert got['component'] == 'blender' and got['exit'] in (2, '2')
    assert 'error: boom' in got['output']


def test_load_failure_absent_is_none(tmp_path):
    paths = Paths(env={'CONFIGSYS_HOME': str(tmp_path)})
    assert reportgen.load_failure(paths) is None


def test_failure_from_result_shape():
    res = type('R', (), {'cmd': 'make', 'returncode': 1, 'output': 'oops'})()
    rec = reportgen.failure_from_result('cargo\\ripgrep', 'cargo', 'install', res)
    assert rec['component'] == 'ripgrep' and rec['unit'] == 'cargo\\ripgrep'
    assert rec['driver'] == 'cargo' and rec['exit'] == 1 and rec['output'] == 'oops'


def test_render_no_captured_output_shows_placeholder():
    payload = {'component': 'x', 'os': {'block': 'pop_os!', 'id': 'pop', 'version': '22.04',
               'pretty': 'Pop!_OS', 'atomic': False},
               'platform': {'kernel': 'Linux', 'arch': 'x86_64', 'python': '3.10'},
               'configsys': {'revision': 'abc', 'abi': 1}, 'profiles': [], 'pins': {},
               'route': None,
               'failure': {'op': 'install', 'unit': 'a\\x', 'driver': 'a', 'exit': 2,
                           'command': 'go', 'output': '', 'at': 't'}}
    body = reportgen.render(payload)
    assert 'not captured' in body and reportgen._MARKER in body
