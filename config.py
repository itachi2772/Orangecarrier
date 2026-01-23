import os

# Heroku vs Local configuration
IS_HEROKU = os.environ.get('DYNO') is not None

if IS_HEROKU:
    # Heroku configuration
    DOWNLOAD_FOLDER = '/tmp'
    BOT_TOKEN = os.environ.get('BOT_TOKEN', 'your_bot_token_here')
    ADMIN_CHAT_ID = os.environ.get('ADMIN_CHAT_ID', 'your_admin_chat_id')
    GROUP_CHAT_ID = os.environ.get('GROUP_CHAT_ID', 'your_group_chat_id')
    LOGIN_URL = os.environ.get('LOGIN_URL', 'https://www.orangecarrier.com/login')
    CALL_URL = os.environ.get('CALL_URL', 'https://www.orangecarrier.com/live/calls')
    BASE_URL = os.environ.get('BASE_URL', 'https://www.orangecarrier.com')
    MAX_ERRORS = int(os.environ.get('MAX_ERRORS', 10))
    CHECK_INTERVAL = int(os.environ.get('CHECK_INTERVAL', 5))
else:
    # Local configuration
    DOWNLOAD_FOLDER = './downloads'
    BOT_TOKEN = 'your_bot_token_here'
    ADMIN_CHAT_ID = 'your_admin_chat_id'
    GROUP_CHAT_ID = 'your_group_chat_id'
    LOGIN_URL = 'https://www.orangecarrier.com/login'
    CALL_URL = 'https://www.orangecarrier.com/live/calls'
    BASE_URL = 'https://www.orangecarrier.com'
    MAX_ERRORS = 10
    CHECK_INTERVAL = 5
