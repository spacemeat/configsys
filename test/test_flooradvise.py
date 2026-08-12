'''Unit tests for flooradvise — the floor-aware advisory (surface-and-choose). versionreport is
mocked, so no network.'''

from configsys import flooradvise, versionreport
from configsys.componentObj import ResolvedComponent
from configsys.routes import Component


class _Routes:
    def __init__(self, components):
        self.components = components


class _Ctx:
    def __init__(self, components):
        self.routes = _Routes(components)
        self.runner = self.paths = None


def _comps():
    return {
        # ripgrep's SOURCE binding requires cargo >=1.96; the native binding requires nothing
        'ripgrep': Component('ripgrep', {'install': [
            {'via': 'native'},
            {'via': 'source', 'requires': [{'cargo': '>=1.96'}]}]}),
        'rust': Component('rust', {'provides': 'cargo',
                                   'install': [{'via': 'native'}, {'via': 'tarball'}]}),
    }


def _rust_report(default_ver, tarball_ver, default_installed=None):
    MV = versionreport.MethodVersion
    return versionreport.VersionReport(name='rust', tip=tarball_ver, methods=[
        MV(via='native', driver='apt', package='rust', latest=default_ver, is_default=True,
           installed=default_installed),
        MV(via='tarball', driver='tarball', package='rust', latest=tarball_ver)])


def _mock(monkeypatch, report):
    monkeypatch.setattr(versionreport, 'report', lambda ctx, name, **k: report)


def _src_unit():
    return ResolvedComponent(key='source\\ripgrep', driver='source', comp='ripgrep', via='source')


def _native_unit():
    return ResolvedComponent(key='apt\\ripgrep', driver='apt', comp='ripgrep', via='native')


def test_advises_when_default_below_floor_and_names_the_pin(monkeypatch):
    _mock(monkeypatch, _rust_report(default_ver='1.75', tarball_ver='1.97'))
    advs = flooradvise.advise(_Ctx(_comps()), [_src_unit()])
    assert len(advs) == 1
    t = advs[0]['text']
    assert 'ripgrep (via source) needs cargo >=1.96' in t
    assert 'provides 1.75' in t
    assert 'pin rust to tarball' in t                      # surface-and-choose: names the fix
    assert advs[0]['level'] == 'warn'


def test_advises_meets_is_singular(monkeypatch):
    _mock(monkeypatch, _rust_report(default_ver='1.75', tarball_ver='1.97'))
    advs = flooradvise.advise(_Ctx(_comps()), [_src_unit()])
    assert 'tarball meets it' in advs[0]['text']            # one method -> "meets", not "meet"


def test_replacement_caveat_when_default_is_installed(monkeypatch):
    # the too-old provider is already installed via the default method -> explicit "won't remove it"
    _mock(monkeypatch, _rust_report(default_ver='1.75', tarball_ver='1.97', default_installed='1.75'))
    advs = flooradvise.advise(_Ctx(_comps()), [_src_unit()])
    assert "installed via native; switching won't remove it" in advs[0]['text']


def test_no_replacement_caveat_when_not_installed(monkeypatch):
    _mock(monkeypatch, _rust_report(default_ver='1.75', tarball_ver='1.97', default_installed=None))
    assert 'switching won' not in flooradvise.advise(_Ctx(_comps()), [_src_unit()])[0]['text']


def test_no_advice_when_default_meets_floor(monkeypatch):
    _mock(monkeypatch, _rust_report(default_ver='1.97', tarball_ver='1.97'))
    assert flooradvise.advise(_Ctx(_comps()), [_src_unit()]) == []


def test_no_advice_for_a_binding_whose_floor_isnt_active(monkeypatch):
    # ripgrep resolved via NATIVE — the source binding's cargo floor is not active, so no advice
    _mock(monkeypatch, _rust_report(default_ver='1.75', tarball_ver='1.97'))
    assert flooradvise.advise(_Ctx(_comps()), [_native_unit()]) == []


def test_no_method_meets_floor_is_stated(monkeypatch):
    # no rust method reaches the floor -> advise, but say there's no fix (don't fabricate a pin)
    _mock(monkeypatch, _rust_report(default_ver='1.75', tarball_ver='1.80'))
    advs = flooradvise.advise(_Ctx(_comps()), [_src_unit()])
    assert len(advs) == 1
    assert 'no install method here meets cargo >=1.96' in advs[0]['text']


def test_abstains_when_default_version_unknown(monkeypatch):
    # the default method's version can't be determined -> no false alarm
    _mock(monkeypatch, _rust_report(default_ver=None, tarball_ver='1.97'))
    assert flooradvise.advise(_Ctx(_comps()), [_src_unit()]) == []


def test_tighten_pins_selects_satisfying_method_for_a_fresh_provider(monkeypatch):
    # auto-tighten (opt-in): a provider whose default is too old + a method that meets it, and the
    # provider is NOT installed -> auto-pin the satisfying method.
    _mock(monkeypatch, _rust_report(default_ver='1.75', tarball_ver='1.97', default_installed=None))
    assert flooradvise.tighten_pins(_Ctx(_comps()), [_src_unit()]) == {'rust': 'tarball'}


def test_tighten_pins_skips_installed_provider_replacement(monkeypatch):
    # the provider is already installed via the too-old default method -> replacement stays
    # explicit (advisory), NEVER auto-tightened.
    _mock(monkeypatch, _rust_report(default_ver='1.75', tarball_ver='1.97', default_installed='1.75'))
    assert flooradvise.tighten_pins(_Ctx(_comps()), [_src_unit()]) == {}


def test_tighten_pins_empty_when_default_already_meets(monkeypatch):
    _mock(monkeypatch, _rust_report(default_ver='1.97', tarball_ver='1.97'))
    assert flooradvise.tighten_pins(_Ctx(_comps()), [_src_unit()]) == {}


def _cuda_comps():
    return {
        # cudnn-8 needs the cuda-toolkit CAPABILITY at <12; two version-scoped providers exist
        'cudnn-8': Component('cudnn-8', {'requires': {'cuda-toolkit': '<12'},
                                         'install': [{'via': 'script'}]}),
        'cuda-toolkit-11': Component('cuda-toolkit-11', {'provides': {'cuda-toolkit': 11},
                                                         'install': [{'via': 'native'}]}),
        'cuda-toolkit-12': Component('cuda-toolkit-12', {'provides': {'cuda-toolkit': 12},
                                                         'install': [{'via': 'native'}]}),
    }


def _cuda_unit():
    return ResolvedComponent(key='script\\cudnn-8', driver='script', comp='cudnn-8', via='script')


def _cuda_report(name):
    MV = versionreport.MethodVersion
    ver = {'cuda-toolkit-11': '11.8', 'cuda-toolkit-12': '12.6.3'}.get(name)
    if ver is None:
        return None
    return versionreport.VersionReport(name=name, tip=ver, methods=[
        MV(via='native', driver='apt', package=name, latest=ver, is_default=True)])


def test_version_scoped_provider_excluded_by_the_constraint_is_not_advised(monkeypatch):
    # cudnn-8 requires cuda-toolkit <12. cuda-toolkit-12 provides 12.6.3 — but the <12 constraint
    # SELECTS cuda-toolkit-11 (11.8, which meets it), so -12 is not this floor's provider at all.
    # The advisory must NOT fire (the false `floor:` warning we were chasing).
    monkeypatch.setattr(versionreport, 'report', lambda ctx, name, **k: _cuda_report(name))
    assert flooradvise.advise(_Ctx(_cuda_comps()), [_cuda_unit()]) == []


def test_active_floors_reads_component_and_winning_binding():
    comps = _comps()
    # via source -> the source binding's cargo floor is active
    assert flooradvise.active_floors(_src_unit(), comps['ripgrep']) == {'cargo': '>=1.96'}
    # via native -> nothing active
    assert flooradvise.active_floors(_native_unit(), comps['ripgrep']) == {}
