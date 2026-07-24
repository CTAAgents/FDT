import pytest

from futures_data_core.core.dominant_resolver import DominantResolver


@pytest.fixture
def resolver(tmp_path):
    r = DominantResolver(storage_path=str(tmp_path / "dominant_map.json"))
    r.load()
    return r
