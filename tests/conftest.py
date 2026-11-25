import pytest

from shelftalk.generate import build
from shelftalk.warehouse import Warehouse


@pytest.fixture(scope="session")
def wh(tmp_path_factory):
    path = tmp_path_factory.mktemp("data") / "shelftalk.db"
    build(path)
    return Warehouse(path)
