from flask_cors import CORS

def init_extensions(app):
    CORS(app, resources={
        r"/api/*": {
            "origins": "*",
            "methods": ["GET", "POST", "PUT", "DELETE", "PATCH"],
            "allow_headers": ["Content-Type", "Authorization"],
            "supports_credentials": True , # ✅ ADD THIS
             "max_age": 3600 
        }
    })
