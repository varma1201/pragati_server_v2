from app import create_app
import os
import socket


config_name = os.getenv('FLASK_ENV', 'development')
app = create_app(config_name)


if __name__ == '__main__':
    # Get PORT from environment variable, default to 8000
    port = int(os.getenv('PORT', 8000))
    
    # Get local IP
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    
    print("="*80)
    print("🚀 FLASK SERVER STARTING")
    print("="*80)
    print(f"Environment: {config_name}")
    print(f"Hostname: {hostname}")
    print(f"Local IP: {local_ip}")
    print(f"Port: {port}")
    print()
    print(f"  - Local: http://localhost:{port}")
    print(f"  - Network: http://{local_ip}:{port}")
    print("="*80)
    print("Updated Version v2")
    
    app.run(
        host='0.0.0.0',  # Listen on all interfaces
        port=port,       # ✅ Use port from .env
        debug=app.config.get('DEBUG', True),
        threaded=True,
        use_reloader=True
    )
