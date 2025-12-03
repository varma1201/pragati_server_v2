from flask import Flask
from app.config import config
from app.extensions import init_extensions
from app.routes import register_blueprints
from app.database.mongo import create_indexes

def create_app(config_name='default'):
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024 
    app.config.from_object(config[config_name])
    
    init_extensions(app)
    register_blueprints(app)
    
    # Create database indexes
    create_indexes()
    
    return app
