import secrets

from flask import Flask

from . import common, database
from .auth import auth_bp
from .chat import chat_bp
from .presence import presence_bp


def create_app():
    app = Flask(__name__)
    app.secret_key = secrets.token_hex(32)
    app.register_blueprint(auth_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(presence_bp)
    return app
