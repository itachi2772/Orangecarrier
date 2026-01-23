import os
import json

# Detect if running on Heroku
IS_HEROKU = os.environ.get('DYNO') is not None

def get_env_var(key, default=None):
    value = os.environ.get(key, default)
    
    # Try to parse JSON for REFRESH_PATTERN
    if key == 'REFRESH_PATTERN' and value:
        try:
            return json.loads(value)
        except:
            pass
    return value

if IS_HEROKU:
    # Heroku Configuration
    DOWNLOAD_FOLDER = '/tmp'
    
    # Telegram Config
    BOT_TOKEN = get_env_var('BOT_TOKEN', '')
    ADMIN_CHAT_ID = get_env_var('ADMIN_CHAT_ID', '')
    GROUP_CHAT_ID = get_env_var('GROUP_CHAT_ID', '')
    
    # Orange Carrier Login Credentials
    ORANGE_EMAIL = get_env_var('ORANGE_EMAIL', '')
    ORANGE_PASSWORD = get_env_var('ORANGE_PASSWORD', '')
    
    # URLs
    LOGIN_URL = get_env_var('LOGIN_URL', 'https://www.orangecarrier.com/login')
    CALL_URL = get_env_var('CALL_URL', 'https://www.orangecarrier.com/live/calls')
    BASE_URL = get_env_var('BASE_URL', 'https://www.orangecarrier.com')
    
    # Settings
    MAX_ERRORS = int(get_env_var('MAX_ERRORS', '10'))
    CHECK_INTERVAL = int(get_env_var('CHECK_INTERVAL', '5'))
    REFRESH_PATTERN = get_env_var('REFRESH_PATTERN', [1800, 1545, 2110, 1850, 1340])
    
else:
    # Local Development Configuration
    DOWNLOAD_FOLDER = './downloads'
    
    # Telegram Config
    BOT_TOKEN = 'YOUR_BOT_TOKEN_HERE'
    ADMIN_CHAT_ID = 'YOUR_ADMIN_CHAT_ID_HERE'
    GROUP_CHAT_ID = 'YOUR_GROUP_CHAT_ID_HERE'
    
    # Orange Carrier Login Credentials
    ORANGE_EMAIL = 'your_email@orangecarrier.com'
    ORANGE_PASSWORD = 'your_password_here'
    
    # URLs
    LOGIN_URL = 'https://www.orangecarrier.com/login'
    CALL_URL = 'https://www.orangecarrier.com/live/calls'
    BASE_URL = 'https://www.orangecarrier.com'
    
    # Settings
    MAX_ERRORS = 10
    CHECK_INTERVAL = 5
    REFRESH_PATTERN = [1800, 1545, 2110, 1850, 1340]

# Create download folder if not exists
import os
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# Print config for debugging
if __name__ == "__main__":
    print("=== Configuration ===")
    print(f"Running on Heroku: {IS_HEROKU}")
    print(f"Download Folder: {DOWNLOAD_FOLDER}")
    print(f"Bot Token Set: {bool(BOT_TOKEN)}")
    print(f"Admin Chat ID: {ADMIN_CHAT_ID}")
    print(f"Group Chat ID: {GROUP_CHAT_ID}")
    print(f"Orange Email: {ORANGE_EMAIL}")
    print(f"Orange Password: {'*' * len(ORANGE_PASSWORD) if ORANGE_PASSWORD else 'Not set'}")
    print(f"Login URL: {LOGIN_URL}")
    print(f"Call URL: {CALL_URL}")
    print(f"Base URL: {BASE_URL}")
    print(f"Max Errors: {MAX_ERRORS}")
    print(f"Check Interval: {CHECK_INTERVAL}")
    print(f"Refresh Pattern: {REFRESH_PATTERN}")
