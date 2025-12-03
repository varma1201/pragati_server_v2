"""
Application Configuration
Environment-specific settings for Pragati Innovation Platform
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Config:
    """Base configuration with common settings"""
    
    # Database
    MONGO_URI = os.getenv("MONGO_URI")
    
    # Authentication
    JWT_SECRET = os.getenv("JWT_SECRET")
    
    # Application
    APP_ID = os.getenv("PRAGATI_APP_ID", "pragati-innovation-suite")
    
    # AWS S3 Configuration
    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
    AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
    S3_BUCKET = os.getenv("S3_BUCKET")
    
    # Email Configuration
    SENDER_EMAIL = os.getenv("SENDERS_EMAIL")
    
    # File Upload
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10MB max upload
    
    # Valid User Roles
    VALID_ROLES = [
        "super_admin",
        "college_admin",
        "ttc_coordinator",
        "innovator",
        "mentor",
        "internal_mentor",
        "team_member"
    ]
    
    # Psychometric Server URL (for external API calls)
    PSYCHOMETRIC_SERVER_URL = os.getenv("PSYCHOMETRIC_SERVER_URL", "http://localhost:5001")
    
    # Rate Limiting (if needed)
    RATELIMIT_ENABLED = os.getenv("RATELIMIT_ENABLED", "False").lower() == "true"
    RATELIMIT_DEFAULT = "100 per hour"


class DevelopmentConfig(Config):
    """Development environment configuration"""
    DEBUG = True
    TESTING = False
    ENV = "development"


class ProductionConfig(Config):
    """Production environment configuration"""
    DEBUG = False
    TESTING = False
    ENV = "production"


class TestingConfig(Config):
    """Testing environment configuration"""
    DEBUG = True
    TESTING = True
    ENV = "testing"


# Configuration dictionary
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}


def get_config(env_name=None):
    """
    Get configuration object based on environment.
    
    Args:
        env_name (str): Environment name (development/production/testing)
        
    Returns:
        Config: Configuration class instance
    """
    if env_name is None:
        env_name = os.getenv('FLASK_ENV', 'development')
    
    return config.get(env_name, config['default'])
