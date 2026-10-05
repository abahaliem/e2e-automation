import pytest

from tests.demo_app.app import DemoServer


@pytest.fixture(scope="session")
def demo_server():
    server = DemoServer().start()
    yield server
    server.stop()


@pytest.fixture
def demo(demo_server):
    demo_server.state.reset()
    return demo_server
