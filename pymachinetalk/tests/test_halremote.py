import pytest

@pytest.fixture
def halremote():
    from pymachinetalk import halremote
    return halremote
