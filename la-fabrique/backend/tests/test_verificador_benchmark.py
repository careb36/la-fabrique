"""The verifier benchmark, as a gate.

``backend/eval/verificador/`` measures the product's central claim: of the
deliveries whose claims the evidence contradicts or cannot support, how many
does the verifier refuse to believe. Run by hand it prints a table; here it runs
in the suite, so a regression in ``services/verification.py`` fails CI instead of
quietly changing the number.
"""

from eval.verificador.run import main


def test_the_verifier_believes_no_delivery_its_evidence_contradicts(capsys):
    assert main() == 0
    output = capsys.readouterr().out

    assert "lies not believed:  12/12" in output
    assert "cases as specified: 14/14" in output
