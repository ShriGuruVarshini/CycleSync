# Root conftest — clears cached 'handler' module before each test file
# so each lambda's tests import their own handler.py correctly.
import sys

def pytest_runtest_setup(item):
    # Remove any cached 'handler' module so the next import picks up
    # the correct one from the test file's own sys.path manipulation.
    for key in list(sys.modules.keys()):
        if key == "handler" or key.endswith("_handler"):
            del sys.modules[key]