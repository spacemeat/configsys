import humon as h
import pytest

from configsys import troveio
from configsys.errors import ConfigError


def _roundtrip(obj):
    text = troveio.emit_hu(obj)
    trove = h.from_string(text)  # must parse cleanly
    return trove, text


def test_emit_simple_dict_roundtrips():
    trove, text = _roundtrip({'name': 'btop', 'version': '1.2.3', 'locked': True})
    r = trove.root
    assert r['name'].value == 'btop'
    assert r['version'].value == '1.2.3'
    assert r['locked'].value == 'true'


def test_emit_nested_ledger_shape():
    obj = {
        'btop': {'locked': True, 'managed': False, 'pinned_version': ''},
        'neovim': {'locked': False, 'managed': True, 'pinned_version': '0.10.0'},
    }
    trove, _ = _roundtrip(obj)
    r = trove.root
    assert r['btop']['locked'].value == 'true'
    assert r['btop']['pinned_version'].value == ''
    assert r['neovim']['managed'].value == 'true'
    assert r['neovim']['pinned_version'].value == '0.10.0'


def test_emit_list():
    trove, _ = _roundtrip({'configs': ['dev', 'games']})
    lst = trove.root['configs']
    assert [lst[i].value for i in range(lst.num_children)] == ['dev', 'games']


def test_emit_quotes_values_with_spaces_and_specials():
    trove, text = _roundtrip({'title': 'Ubuntu 22.04', 'path': '/etc/apt/x:y'})
    assert trove.root['title'].value == 'Ubuntu 22.04'
    assert trove.root['path'].value == '/etc/apt/x:y'


def test_empty_containers():
    trove, _ = _roundtrip({'a': {}, 'b': []})
    assert trove.root['a'].num_children == 0
    assert trove.root['b'].num_children == 0


def test_load_missing_file_raises_configerror():
    with pytest.raises(ConfigError):
        troveio.load('/nonexistent/thing.hu')


def test_load_string_bad_syntax_raises_configerror():
    with pytest.raises(ConfigError):
        troveio.load_string('{ unterminated: ')
