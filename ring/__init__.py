from .helpers import setup as helpers_setup

from app_types import Application


def setup(app: Application):
    helpers_setup(app)