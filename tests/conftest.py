import os

import pytest

# Qt needs a platform plugin; CI and headless Raspberry Pi units have no display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def app():
    from aion_show_system.app import create_app

    return create_app([])
