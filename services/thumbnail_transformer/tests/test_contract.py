from pathlib import Path


def test_contract_surface():
    text = Path(__file__).parents[1].joinpath("app/main.py").read_text()
    assert 'x-mreader-transform-token' in text
    assert 'MAX_INPUT_BYTES' in text
    assert 'Cache-Control' in text and 'no-store' in text
    assert '/v1/thumbnail' in text
