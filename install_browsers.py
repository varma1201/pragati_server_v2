import os
import subprocess
import sys

def install_browsers():
    print("Installing Playwright browsers...")
    try:
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
        print("Successfully installed Chromium.")
    except subprocess.CalledProcessError as e:
        print(f"Error installing browsers: {e}")
        sys.exit(1)

if __name__ == "__main__":
    install_browsers()
