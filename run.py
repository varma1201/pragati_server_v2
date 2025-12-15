from app import create_app
import os
import socket

config_name = os.getenv('FLASK_ENV', 'development')
app = create_app(config_name)

if __name__ == '__main__':
    # Get local IP
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    
    print("="*80)
    print("🚀 FLASK SERVER STARTING")
    print("="*80)
    print(f"Environment: {config_name}")
    print(f"Hostname: {hostname}")
    print(f"Local IP: {local_ip}")
    print(f"Port: 8000")
    print("")
    print("Access server at:")
    print(f"  - Local:   http://localhost:8000")
    print(f"  - Local:   http://127.0.0.1:8000")
    print(f"  - Network: http://{local_ip}:8000")
    print("="*80)
    
    app.run(
        host='0.0.0.0',  # Listen on all interfaces
        port=8000,
        debug=app.config.get('DEBUG', True),
        threaded=True,
        use_reloader=True
    )
