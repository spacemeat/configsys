'''A `facets: { detect: … }` probe runs shell on every resolve, so it is command-carrying data: the
repo's facets always merge, but a PLUGIN's facets merge only when that plugin is content-trusted
(command_trust), with an actionable warning otherwise — never blanket-refused (regression for the
over-broad A2 fix that broke the trusted configsys-opencv `cuda` facet).'''

from configsys.routes import load

REPO = '{ os: { linux: {}  debian: { using: linux  native: apt } }  components: { } }'
PLUG = ('{ facets: { gpu: { kind: categorical  detect: "echo nvidia"  '
        'match: { nvidia: "nvidia" } } } }')


def _load(tmp_path, trust):
    (tmp_path / 'routes.hu').write_text(REPO)
    (tmp_path / 'plug.hu').write_text(PLUG)
    warns = []
    casc, _c, _d, _co = load(str(tmp_path / 'routes.hu'), None,
                             [(str(tmp_path / 'plug.hu'), 'plugin')],
                             warnings_out=warns, command_trust=trust)
    return casc, warns


def test_untrusted_plugin_facets_are_dropped_with_a_warning(tmp_path):
    casc, warns = _load(tmp_path, lambda _p: False)
    assert 'gpu' not in casc.facet_specs
    assert any('untrusted plugin' in w and 'plugin trust' in w for w in warns)


def test_trusted_plugin_facets_merge(tmp_path):
    casc, warns = _load(tmp_path, lambda _p: True)
    assert 'gpu' in casc.facet_specs                 # a trusted plugin gets its hardware probe
    assert not any('untrusted' in w for w in warns)


def test_no_command_trust_predicate_allows_plugin_facets(tmp_path):
    # back-compat: callers/tests that don't pass command_trust keep the old permissive merge
    casc, _warns = _load(tmp_path, None)
    assert 'gpu' in casc.facet_specs
