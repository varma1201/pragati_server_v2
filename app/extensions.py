from flask_cors import CORS

def init_extensions(app):
    CORS(app, resources={
        r"/api/*": {
            "origins": [r"^https?://.*"],  # ✅ Allow all origins with regex to support credentials
            "methods": ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization", "X-Requested-With"],
            "supports_credentials": True,
            "max_age": 3600
        }
    })
