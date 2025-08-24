import os
from flask import Flask
from flask_socketio import SocketIO

from routes.main_routes import main_bp
from routes.api_routes import api_bp
from routes.socket_routes import register_socket_events


def create_app(config=None):
    """Create and configure the Flask application"""
    # Get the directory where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    template_dir = os.path.join(script_dir, "templates")
    
    app = Flask(__name__, template_folder=template_dir)
    app.config["SECRET_KEY"] = os.urandom(24)
    
    # Apply configuration if provided
    if config:
        app.config.update(config)
    
    # Register blueprints
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp)
    
    # Initialize SocketIO
    socketio = SocketIO(app, cors_allowed_origins="*")
    
    # Register socket events
    register_socket_events(socketio, app)
    
    return app, socketio