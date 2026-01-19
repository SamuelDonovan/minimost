# From the python standard library
import secrets

# From Flask 
from flask import Flask

# Local imports
import common 
import database 
from auth import auth_bp
from chat import chat_bp

def create_app():
    app = Flask(__name__)
    app.secret_key = secrets.token_hex(32)
    app.register_blueprint(auth_bp)
    app.register_blueprint(chat_bp)
    return app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
