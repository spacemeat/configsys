from configsys import failures
from configsys.runner import Result


def test_no_pubkey_is_signature_with_key_id():
    cat, rem = failures.classify(
        "W: GPG error: https://pkg.jenkins.io/debian-stable binary/ Release: The following "
        "signatures couldn't be verified because the public key is not available: "
        "NO_PUBKEY 7198F4B714ABFC68")
    assert cat == failures.SIGNATURE
    assert '7198F4B714ABFC68' in rem


def test_not_signed_is_signature():
    cat, _ = failures.classify("E: The repository 'https://x binary/ Release' is not signed.")
    assert cat == failures.SIGNATURE


def test_network_failure():
    cat, _ = failures.classify('Could not resolve host: github.com')
    assert cat == failures.NETWORK


def test_404_is_not_found():
    cat, _ = failures.classify('curl: (22) The requested URL returned error: 404 Not Found')
    assert cat == failures.NOT_FOUND


def test_missing_package_is_dependency():
    cat, _ = failures.classify('E: Unable to locate package definitely-not-a-package')
    assert cat == failures.DEPENDENCY


def test_build_failure():
    cat, _ = failures.classify("make[1]: *** [Makefile:42: all] Error 2")
    assert cat == failures.BUILD


def test_unrecognised_is_none():
    assert failures.classify('some totally novel error nobody has a rule for') == (None, None)
    assert failures.classify('') == (None, None)


def test_result_classified_infers_from_output():
    r = Result('apt-get update', 1, stderr='NO_PUBKEY 7198F4B714ABFC68')
    assert r.classified()[0] == failures.SIGNATURE


def test_result_explicit_category_wins_over_inference():
    # a driver that tags the failure keeps its tag even if the text would classify differently
    r = Result.fail('the network is down', category=failures.NETWORK, remediation='check the cable')
    assert r.classified() == (failures.NETWORK, 'check the cable')


def test_result_clean_output_is_unclassified():
    assert Result('x', 1, stderr='exit 1').classified() == (None, None)


# -- retry_transient -----------------------------------------------------------------------------

def _seq(results):
    '''A run() that returns each Result in turn (last repeats).'''
    box = {'i': 0}
    def run():
        i = min(box['i'], len(results) - 1)
        box['i'] += 1
        return results[i]
    run.count = lambda: box['i']
    return run


def test_retry_transient_recovers_from_a_blip():
    # a transient "could not be read" on the first try, then success -> returns ok, no scary failure
    run = _seq([Result('u', 1, stderr='E: The list of sources could not be read.'),
                Result('u', 0)])
    res = failures.retry_transient(run, tries=3, sleep=lambda s: None)
    assert res.ok and run.count() == 2


def test_retry_transient_gives_up_after_tries():
    run = _seq([Result('u', 1, stderr='E: The list of sources could not be read.')])  # never recovers
    res = failures.retry_transient(run, tries=3, sleep=lambda s: None)
    assert not res.ok and run.count() == 3          # exhausted all attempts


def test_retry_transient_does_not_retry_a_definitive_failure():
    # a signature error names a repo/key — retrying can't change it, so return on the first try
    run = _seq([Result('u', 1, stderr='NO_PUBKEY 7198F4B714ABFC68')])
    res = failures.retry_transient(run, tries=5, sleep=lambda s: None)
    assert not res.ok and run.count() == 1
