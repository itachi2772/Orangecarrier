import os
import json

# Heroku vs Local
IS_HEROKU = os.environ.get('DYNO') is not None

if IS_HEROKU:
    # Heroku config
    BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
    ADMIN_CHAT_ID = os.environ.get('ADMIN_CHAT_ID', '')
    GROUP_CHAT_ID = os.environ.get('GROUP_CHAT_ID', '')
    
    # Orange Carrier Login Credentials (fallback)
    ORANGE_EMAIL = os.environ.get('ORANGE_EMAIL', '')
    ORANGE_PASSWORD = os.environ.get('ORANGE_PASSWORD', '')
    
    # URLs
    LOGIN_URL = os.environ.get('LOGIN_URL', 'https://www.orangecarrier.com/login')
    CALL_URL = os.environ.get('CALL_URL', 'https://www.orangecarrier.com/live/calls')
    BASE_URL = os.environ.get('BASE_URL', 'https://www.orangecarrier.com')
    
    # Cookies from environment variable (JSON string)
    cookies_env = os.environ.get('ORANGE_COOKIES', '')
    ORANGE_COOKIES = json.loads(cookies_env) if cookies_env else []
    
    # Settings
    MAX_ERRORS = int(os.environ.get('MAX_ERRORS', '10'))
    CHECK_INTERVAL = int(os.environ.get('CHECK_INTERVAL', '5'))
    
else:
    # Local development Configuration
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
    
    # Cookies (paste your cookies here as Python list)
    ORANGE_COOKIES = [
        # Paste your cookies here in the same format
        {
            "domain": ".orangecarrier.com",
            "expirationDate": 1803729122.883909,
            "hostOnly": False,
            "httpOnly": False,
            "name": "_ga",
            "path": "/",
            "sameSite": "unspecified",
            "secure": False,
            "session": False,
            "storeId": "0",
            "value": "GA1.2.1935366298.1768217292"
        },
        # ... add all other cookies
    ]
    
    # Settings
    MAX_ERRORS = 10
    CHECK_INTERVAL = 5
