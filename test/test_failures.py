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
