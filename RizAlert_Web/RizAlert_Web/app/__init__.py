from flask import Flask
from .configs import Config
from .firebase_config import initialize_firebase
from datetime import datetime

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config['DEBUG'] = True
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.config.from_object(config_class)

    # Initialize Firebase
    initialize_firebase()
    
    # Register blueprints
    from app.routes import main, api
    app.register_blueprint(main)
    app.register_blueprint(api, url_prefix='/api')
    
    # Custom Jinja2 filter for time ago
    def time_ago(seconds):
        seconds = abs(seconds)
        if seconds < 60:
            return f"{int(seconds)} seconds ago"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        elif seconds < 86400:
            hours = int(seconds // 3600)
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        else:
            days = int(seconds // 86400)
            return f"{days} day{'s' if days != 1 else ''} ago"

    app.jinja_env.filters['time_ago'] = time_ago

    return app