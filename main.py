import time
import re
import requests
import os
import random
import json
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
import phonenumbers
from phonenumbers import region_code_for_number
import pycountry
import config
import speech_recognition as sr
from pydub import AudioSegment
import io

active_calls = {}
processing_calls = set()
refresh_pattern_index = 0

# Updated refresh pattern as requested
REFRESH_PATTERN = [1800, 1545, 2110, 1850, 1340]  # seconds

# Heroku-compatible download folder
DOWNLOAD_FOLDER = '/tmp' if os.environ.get('DYNO') else './downloads'
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

def human_like_delay(min_seconds=1, max_seconds=3):
    """Human-like random delay"""
    time.sleep(random.uniform(min_seconds, max_seconds))

def human_like_mouse_movement(driver, element):
    """Simulate human-like mouse movement"""
    try:
        # Get element location
        location = element.location
        size = element.size
        
        # Move to random position within element
        offset_x = random.randint(0, size['width'] // 2)
        offset_y = random.randint(0, size['height'] // 2)
        
        action = ActionChains(driver)
        action.move_to_element_with_offset(element, offset_x, offset_y)
        action.pause(random.uniform(0.1, 0.3))
        action.click()
        action.perform()
    except:
        # Fallback to simple click
        element.click()

def get_next_refresh_time():
    """Get next refresh time using the specified pattern"""
    global refresh_pattern_index
    
    interval = REFRESH_PATTERN[refresh_pattern_index]
    
    # Move to next pattern (cycle through the 5 intervals)
    refresh_pattern_index = (refresh_pattern_index + 1) % len(REFRESH_PATTERN)
    
    print(f"[🔄] Next refresh in {interval} seconds ({interval//60} minutes {interval%60} seconds)")
    return interval

def country_to_flag(country_code):
    """Convert country code to flag emoji"""
    if not country_code or len(country_code) != 2:
        return "🏳️"
    return "".join(chr(127397 + ord(c)) for c in country_code.upper())

def detect_country(number):
    """Detect country from phone number"""
    try:
        clean_number = re.sub(r"\D", "", number)
        if clean_number:
            parsed = phonenumbers.parse("+" + clean_number, None)
            region = region_code_for_number(parsed)
            country = pycountry.countries.get(alpha_2=region)
            if country:
                return country.name, country_to_flag(region)
    except:
        pass
    return "Unknown", "🏳️"

def send_message_to_admin(text):
    """Send message to Admin Telegram (Full number + URL only)"""
    try:
        url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage"
        payload = {"chat_id": config.ADMIN_CHAT_ID, "text": text, "parse_mode": "Markdown"}
        res = requests.post(url, json=payload, timeout=10)
        if res.ok:
            return res.json().get("result", {}).get("message_id")
    except Exception as e:
        print(f"[❌] Failed to send message to admin: {e}")
    return None

def send_message_to_group(text):
    """Send message to Group Telegram"""
    try:
        url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage"
        payload = {"chat_id": config.GROUP_CHAT_ID, "text": text, "parse_mode": "HTML"}
        res = requests.post(url, json=payload, timeout=10)
        if res.ok:
            return res.json().get("result", {}).get("message_id")
    except Exception as e:
        print(f"[❌] Failed to send message to group: {e}")
    return None

def delete_message(chat_id, msg_id):
    """Delete message from Telegram"""
    try:
        url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/deleteMessage"
        requests.post(url, data={"chat_id": chat_id, "message_id": msg_id}, timeout=5)
    except:
        pass

def send_voice_to_group(voice_path, caption):
    """Send voice recording with caption to Group Telegram"""
    try:
        if os.path.getsize(voice_path) < 1000:
            raise ValueError("File too small or empty")
        url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendVoice"
        with open(voice_path, "rb") as voice:
            payload = {"chat_id": config.GROUP_CHAT_ID, "caption": caption, "parse_mode": "HTML"}
            files = {"voice": voice}
            response = requests.post(url, data=payload, files=files, timeout=60)
            if response.status_code == 200:
                return True
            else:
                print(f"[DEBUG] Telegram response: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"[❌] Failed to send voice to group: {e}")
    return False

def extract_otp_from_audio(audio_path):
    """Extract OTP from audio file (English + Spanish)"""
    try:
        print(f"[🎯] Attempting OTP extraction from: {audio_path}")
        
        # Convert audio to WAV format for speech recognition
        audio = AudioSegment.from_file(audio_path)
        
        # Normalize audio
        audio = audio.normalize()
        
        # Export as WAV
        wav_data = io.BytesIO()
        audio.export(wav_data, format="wav")
        wav_data.seek(0)
        
        # Initialize recognizer
        r = sr.Recognizer()
        
        with sr.AudioFile(wav_data) as source:
            # Adjust for ambient noise
            r.adjust_for_ambient_noise(source, duration=0.5)
            audio_data = r.record(source)
        
        # Try English first
        try:
            text = r.recognize_google(audio_data, language='en-US')
            print(f"[🔤] English transcription: {text}")
        except sr.UnknownValueError:
            # Try Spanish if English fails
            try:
                text = r.recognize_google(audio_data, language='es-ES')
                print(f"[🔤] Spanish transcription: {text}")
            except sr.UnknownValueError:
                print("[❌] Could not understand audio in either English or Spanish")
                return None
        except Exception as e:
            print(f"[❌] Speech recognition error: {e}")
            return None
        
        # Enhanced OTP pattern matching
        otp_patterns = [
            r'\b\d{4,6}\b',  # 4-6 digit OTP
            r'code[\s\:\-]*(\d{4,6})',  # "code: 1234"
            r'verification[\s\:\-]*(\d{4,6})',  # "verification 1234"
            r'password[\s\:\-]*(\d{4,6})',  # "password 1234"
            r'OTP[\s\:\-]*(\d{4,6})',  # "OTP 1234"
            r'pin[\s\:\-]*(\d{4,6})',  # "pin 1234"
            r'(\d{4,6})[\s]*is[\s]*your',  # "1234 is your"
            r'your[\s]*code[\s]*is[\s]*(\d{4,6})',  # "your code is 1234"
            r'código[\s\:\-]*(\d{4,6})',  # Spanish "código 1234"
            r'verificación[\s\:\-]*(\d{4,6})',  # Spanish "verificación 1234"
        ]
        
        for pattern in otp_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                otp = matches[0] if isinstance(matches[0], str) else matches[0][0] if matches[0] else None
                if otp and otp.isdigit():
                    print(f"[✅] OTP detected: {otp}")
                    return otp
        
        # If no pattern matches, look for any 4-6 digit sequence
        digit_matches = re.findall(r'\b\d{4,6}\b', text)
        if digit_matches:
            print(f"[🔢] Potential OTP found: {digit_matches[0]}")
            return digit_matches[0]
        
        print(f"[❌] No OTP found in transcription: {text}")
        return None
        
    except Exception as e:
        print(f"[💥] OTP extraction error: {e}")
        return None

def load_cookies_from_config():
    """Load cookies from config or environment variable"""
    cookies_json = None
    
    try:
        # Try to get cookies from environment variable
        cookies_env = os.environ.get('ORANGE_COOKIES')
        if cookies_env:
            cookies_json = json.loads(cookies_env)
            print(f"[🍪] Loaded {len(cookies_json)} cookies from environment")
            return cookies_json
        
        # Try to get from config
        if hasattr(config, 'ORANGE_COOKIES') and config.ORANGE_COOKIES:
            cookies_json = config.ORANGE_COOKIES
            print(f"[🍪] Loaded {len(cookies_json)} cookies from config")
            return cookies_json
        
        # Default cookies (the ones you provided)
        default_cookies = [
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
            {
                "domain": ".orangecarrier.com",
                "expirationDate": 1776945130,
                "hostOnly": False,
                "httpOnly": False,
                "name": "_fbp",
                "path": "/",
                "sameSite": "lax",
                "secure": False,
                "session": False,
                "storeId": "0",
                "value": "fb.1.1768217293096.854589425594967818"
            },
            {
                "domain": ".orangecarrier.com",
                "expirationDate": 1769255522,
                "hostOnly": False,
                "httpOnly": False,
                "name": "_gid",
                "path": "/",
                "sameSite": "unspecified",
                "secure": False,
                "session": False,
                "storeId": "0",
                "value": "GA1.2.236214399.1769169118"
            },
            {
                "domain": ".orangecarrier.com",
                "expirationDate": 1769169178,
                "hostOnly": False,
                "httpOnly": False,
                "name": "_gat_gtag_UA_191466370_1",
                "path": "/",
                "sameSite": "unspecified",
                "secure": False,
                "session": False,
                "storeId": "0",
                "value": "1"
            },
            {
                "domain": "www.orangecarrier.com",
                "expirationDate": 1769176333.581938,
                "hostOnly": True,
                "httpOnly": False,
                "name": "XSRF-TOKEN",
                "path": "/",
                "sameSite": "unspecified",
                "secure": False,
                "session": False,
                "storeId": "0",
                "value": "eyJpdiI6IjlhOHVyWkRvcUdTQVdTU0RzU3NWWWc9PSIsInZhbHVlIjoiRE42cFVVZ01tckNybTVkQmNRazZKcjhRTkFybWZCdDZTYXZvY2RuNUc2M05cLzdST0d5cEhEeXFYMktNNE9SQVJTSEZSZUpleU1PVm9tYmVVM3ZKVmFualhPalFcLzhqM0tldDVCQjFRUk1PdDFaSXpkaFwvOURyWjdaMW1WV1Q3QysiLCJtYWMiOiI1Yjg1NThmNmZiZjZkZGJmNmUyZmE0MzM3NzIyYTEzMzNkMTczYjAyMmIzYmM5YjczZGMxNWJmNzg3M2E0MzMyIn0%3D"
            },
            {
                "domain": "www.orangecarrier.com",
                "expirationDate": 1769176333.582121,
                "hostOnly": True,
                "httpOnly": True,
                "name": "orange_carrier_session",
                "path": "/",
                "sameSite": "unspecified",
                "secure": False,
                "session": False,
                "storeId": "0",
                "value": "eyJpdiI6Ino1XC81M0tkUnZDTDBCNmQ4Nkc3QlFRPT0iLCJ2YWx1ZSI6InBXdEY4SmowWEFmYzNGY0NDY21PekhmZjJLSmNwV0NZSXgwY3hmaGhKVWhiQ3c1dXNJUFVuZHN0RHdKNEw3b3JrYmxzMFh0czF0M0xmK0NoNkdUZmkwWFMyMWhNZko3QU5PcFJJODgySEpidUpBeFdTYklZeEM4Q05rbnNNMUtYIiwibWFjIjoiNzU2Zjc3OTZlMjg4ZWUwOWFmNzk0ZTljMTJkOGNlMjQ2ZTkzYzJkMWZmZTVhYTc0MTU1MTAzZTljYjE0NmNhZCJ9"
            }
        ]
        
        print(f"[🍪] Using default {len(default_cookies)} cookies")
        return default_cookies
        
    except Exception as e:
        print(f"[❌] Error loading cookies: {e}")
        return []

def setup_chrome_driver_with_cookies():
    """Setup Chrome driver and load cookies for authentication"""
    chrome_options = Options()
    
    # Heroku-specific settings
    is_heroku = os.environ.get('DYNO') is not None
    
    if is_heroku:
        chrome_options.binary_location = os.environ.get('GOOGLE_CHROME_BIN', '/app/.apt/usr/bin/google-chrome')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        # Set user agent
        chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        
        # Heroku Chrome path
        driver_path = os.environ.get('CHROMEDRIVER_PATH', '/app/.chromedriver/bin/chromedriver')
        print(f"[🔧] Using Chrome binary: {chrome_options.binary_location}")
        print(f"[🔧] Using Chromedriver: {driver_path}")
        
        driver = webdriver.Chrome(
            executable_path=driver_path,
            options=chrome_options
        )
    else:
        # Local development
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        driver = webdriver.Chrome(options=chrome_options)
    
    # Load cookies
    cookies = load_cookies_from_config()
    
    if cookies:
        try:
            # First navigate to domain to set cookies
            driver.get("https://www.orangecarrier.com")
            time.sleep(2)
            
            # Delete existing cookies
            driver.delete_all_cookies()
            time.sleep(1)
            
            # Add new cookies
            for cookie in cookies:
                try:
                    # Remove unwanted keys that Selenium doesn't support
                    cookie_copy = cookie.copy()
                    
                    # Convert expirationDate from double to integer if needed
                    if 'expirationDate' in cookie_copy:
                        cookie_copy['expiry'] = int(cookie_copy['expirationDate'])
                        del cookie_copy['expirationDate']
                    
                    # Remove unsupported keys
                    unsupported_keys = ['hostOnly', 'storeId', 'sameSite']
                    for key in unsupported_keys:
                        if key in cookie_copy:
                            del cookie_copy[key]
                    
                    # Add cookie to driver
                    driver.add_cookie(cookie_copy)
                    print(f"[✅] Added cookie: {cookie_copy.get('name')}")
                    
                except Exception as e:
                    print(f"[⚠️] Failed to add cookie {cookie.get('name')}: {e}")
            
            # Refresh to apply cookies
            driver.refresh()
            time.sleep(3)
            print(f"[🍪] Successfully loaded {len(cookies)} cookies")
            
        except Exception as e:
            print(f"[❌] Error setting cookies: {e}")
    
    driver.set_page_load_timeout(60)
    return driver

def login_with_cookies(driver):
    """Login to Orange Carrier using cookies"""
    try:
        print("[🔐] Attempting login with cookies...")
        
        # Navigate to login page first
        driver.get(config.LOGIN_URL)
        time.sleep(3)
        
        # Check if we're already logged in
        current_url = driver.current_url
        if "dashboard" in current_url or "live/calls" in current_url:
            print("[✅] Already logged in via cookies!")
            return True
        
        # If not logged in, try to access calls page directly
        driver.get(config.CALL_URL)
        time.sleep(3)
        
        # Check for login page redirect
        if "login" in driver.current_url:
            print("[❌] Cookies expired or invalid")
            return False
        
        # Check for LiveCalls table
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "LiveCalls"))
            )
            print("[✅] Login successful with cookies!")
            return True
        except:
            # Try alternative method - check for any dashboard element
            page_source = driver.page_source
            if "Dashboard" in page_source or "Live Calls" in page_source:
                print("[✅] Login successful (alternative check)!")
                return True
            
            print("[❌] Could not verify login status")
            return False
            
    except Exception as e:
        print(f"[💥] Cookie login error: {e}")
        return False

def extract_calls(driver):
    """Extract call information from the calls table"""
    global active_calls, processing_calls
    
    try:
        calls_table = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "LiveCalls"))
        )
        
        rows = calls_table.find_elements(By.TAG_NAME, "tr")
        current_call_ids = set()
        
        for row in rows:
            try:
                row_id = row.get_attribute('id')
                if not row_id:
                    continue
                    
                cells = row.find_elements(By.TAG_NAME, "td")
                if len(cells) < 5:
                    continue
                
                did_element = cells[1]
                did_text = did_element.text.strip()
                did_number = re.sub(r"\D", "", did_text)
                
                if not did_number:
                    continue
                
                current_call_ids.add(row_id)
                
                if row_id not in active_calls:
                    print(f"[📞] New call detected: {did_number}")
                    
                    country_name, flag = detect_country(did_number)
                    
                    # Build full URL
                    full_url = f"https://www.orangecarrier.com/live/calls/sound?did={did_number}&uuid={row_id}"
                    
                    # Send to ADMIN only (Full number + URL) - NO POST CONTENT
                    admin_text = f"📞 {did_number}\n🔗 {full_url}"
                    
                    msg_id = send_message_to_admin(admin_text)
                    active_calls[row_id] = {
                        "admin_msg_id": msg_id,
                        "flag": flag,
                        "country": country_name,
                        "did_number": did_number,
                        "call_uuid": row_id,
                        "detected_at": datetime.now(),
                        "last_seen": datetime.now(),
                        "full_url": full_url
                    }
                else:
                    active_calls[row_id]["last_seen"] = datetime.now()
                    
            except StaleElementReferenceException:
                continue
            except Exception as e:
                print(f"[❌] Row processing error: {e}")
                continue
        
        current_time = datetime.now()
        completed_calls = []
        
        # Find completed calls
        for call_id, call_info in list(active_calls.items()):
            if (call_id not in current_call_ids) and (call_id not in processing_calls):
                print(f"[✅] Call completed: {call_info['did_number']}")
                completed_calls.append(call_id)
        
        # Process completed calls immediately
        for call_id in completed_calls:
            call_info = active_calls[call_id]
            
            # Mark as processing to avoid duplicate processing
            processing_calls.add(call_id)
            
            # Delete the admin monitoring message
            if call_info["admin_msg_id"]:
                delete_message(config.ADMIN_CHAT_ID, call_info["admin_msg_id"])
            
            # Start recording process in a separate thread to avoid blocking
            import threading
            thread = threading.Thread(
                target=process_completed_call,
                args=(driver, call_info, call_id)
            )
            thread.daemon = True
            thread.start()
            
            # Remove from active calls
            del active_calls[call_id]
                
    except TimeoutException:
        print("[⏱️] No active calls table found")
    except Exception as e:
        print(f"[❌] Error extracting calls: {e}")

def process_completed_call(driver, call_info, call_uuid):
    """Process completed call - download voice and extract OTP"""
    try:
        print(f"[🎙️] Processing completed call: {call_info['did_number']}")
        
        # Create unique filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = os.path.join(DOWNLOAD_FOLDER, f"call_{call_info['did_number']}_{timestamp}.mp3")
        
        # Try to download the voice recording
        if download_voice_recording(driver, call_info, call_uuid, file_path):
            # Send to GROUP with voice (OTP removed)
            send_to_group_with_voice(call_info, file_path)
        else:
            # If download fails, send failure message to group
            send_download_failed_to_group(call_info)
        
        # Clean up processing set
        if call_uuid in processing_calls:
            processing_calls.remove(call_uuid)
            
    except Exception as e:
        print(f"[💥] Call processing error: {e}")
        if call_uuid in processing_calls:
            processing_calls.remove(call_uuid)

def download_voice_recording(driver, call_info, call_uuid, file_path):
    """Download voice recording using direct download method"""
    try:
        print("[🔄] Trying enhanced direct download...")
        
        # Simulate play button first
        play_script = f'window.Play("{call_info["did_number"]}", "{call_uuid}"); return true;'
        driver.execute_script(play_script)
        time.sleep(5)
        
        # Get all cookies and session data
        cookies = driver.get_cookies()
        session = requests.Session()
        
        for cookie in cookies:
            session.cookies.set(cookie['name'], cookie['value'])
        
        # Enhanced headers
        headers = {
            'User-Agent': driver.execute_script("return navigator.userAgent;"),
            'Accept': 'audio/mpeg, audio/*, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': config.CALL_URL,
            'Origin': 'https://www.orangecarrier.com',
            'Sec-Fetch-Dest': 'audio',
            'Sec-Fetch-Mode': 'no-cors',
            'Sec-Fetch-Site': 'same-origin',
            'X-Requested-With': 'XMLHttpRequest'
        }
        
        # Use the full URL we already built
        recording_url = call_info['full_url']
        
        response = session.get(recording_url, headers=headers, timeout=30, stream=True)
        
        if response.status_code == 200:
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            file_size = os.path.getsize(file_path)
            if file_size > 1000:
                print(f"[✅] Voice download successful: {file_size} bytes")
                return True
        
        print(f"[❌] Voice download failed: {response.status_code}")
        return False
        
    except Exception as e:
        print(f"[❌] Voice download error: {e}")
        return False

def send_to_group_with_voice(call_info, file_path):
    """Send voice recording to group with masked number format (OTP removed)"""
    try:
        call_time = call_info['detected_at'].strftime('%Y-%m-%d %I:%M:%S %p')
        
        # Mask the phone number in format: 8559****473
        number = call_info['did_number']
        if len(number) >= 8:
            # Show first 4 digits, then 4 asterisks, then last 3 digits
            masked_number = number[:4] + "****" + number[-3:]
        else:
            # Fallback for shorter numbers
            masked_number = number[:4] + "****" + number[4:]
        
        # Build caption in the requested format
        caption = (
            "📳 New Call Captured!\n\n"
            f"└ ⏰ Time: {call_time}\n"
            f"└ {call_info['flag']} {call_info['country']}\n"
            f"└ 📞 Number: {masked_number}\n"
        )
        
        # Send voice to group
        if send_voice_to_group(file_path, caption):
            print(f"[✅] Voice sent to group successfully: {call_info['did_number']}")
        else:
            # Fallback with text message in same format
            text_fallback = (
                "📳 New Call Captured!\n\n"
                f"└ ⏰ Time: {call_time}\n"
                f"└ {call_info['flag']} {call_info['country']}\n"
                f"└ 📞 Number: {masked_number}\n"
            )
            
            send_message_to_group(text_fallback)
            
        # Clean up file
        try:
            os.remove(file_path)
        except:
            pass
            
    except Exception as e:
        print(f"[❌] Error sending to group: {e}")

def send_download_failed_to_group(call_info):
    """Send download failure message to group in masked number format"""
    try:
        call_time = call_info['detected_at'].strftime('%Y-%m-%d %I:%M:%S %p')
        
        # Mask the phone number in format: 8559****473
        number = call_info['did_number']
        if len(number) >= 8:
            # Show first 4 digits, then 4 asterisks, then last 3 digits
            masked_number = number[:4] + "****" + number[-3:]
        else:
            # Fallback for shorter numbers
            masked_number = number[:4] + "****" + number[4:]
        
        failure_text = (
            "😟 Please contact group admin for error call OTP\n\n"
            f"└ ⏰ Time: {call_time}\n"
            f"└ {call_info['flag']} {call_info['country']}\n"
            f"└ 📞 Number: {masked_number}\n"
            f"└ ❌ Voice download failed\n"
        )
        
        send_message_to_group(failure_text)
        print(f"[❌] Download failed notification sent to group: {call_info['did_number']}")
        
    except Exception as e:
        print(f"[❌] Error sending failure message: {e}")

def check_login_status(driver):
    """Check if user is still logged in"""
    try:
        # Check current URL
        if "login" in driver.current_url:
            return False
        
        # Check for logout button or user profile
        logout_indicators = [
            "a[href*='logout']",
            ".user-profile",
            ".account-menu"
        ]
        
        for selector in logout_indicators:
            try:
                if driver.find_elements(By.CSS_SELECTOR, selector):
                    return True
            except:
                continue
        
        # Check for login form elements
        login_form_elements = ["input[type='email']", "input[type='password']", "#login-form"]
        for selector in login_form_elements:
            try:
                if driver.find_elements(By.CSS_SELECTOR, selector):
                    return False
            except:
                continue
        
        return True
        
    except:
        return False

def refresh_with_cookies(driver):
    """Refresh page and re-apply cookies if needed"""
    try:
        print("[🔄] Refreshing page...")
        driver.refresh()
        time.sleep(5)
        
        # Check if we got logged out
        if not check_login_status(driver):
            print("[⚠️] Session expired, re-applying cookies...")
            # Re-apply cookies
            cookies = load_cookies_from_config()
            if cookies:
                driver.delete_all_cookies()
                for cookie in cookies:
                    try:
                        cookie_copy = cookie.copy()
                        if 'expirationDate' in cookie_copy:
                            cookie_copy['expiry'] = int(cookie_copy['expirationDate'])
                            del cookie_copy['expirationDate']
                        
                        unsupported_keys = ['hostOnly', 'storeId', 'sameSite']
                        for key in unsupported_keys:
                            if key in cookie_copy:
                                del cookie_copy[key]
                        
                        driver.add_cookie(cookie_copy)
                    except:
                        continue
                
                driver.refresh()
                time.sleep(5)
        
        return True
        
    except Exception as e:
        print(f"[❌] Refresh error: {e}")
        return False

def main():
    print("[🚀] Starting Orange Carrier Monitor with Cookies...")
    
    driver = None
    try:
        # Setup Chrome driver with cookies
        driver = setup_chrome_driver_with_cookies()
        
        # Login with cookies
        if not login_with_cookies(driver):
            print("[❌] Cookie login failed, attempting manual login...")
            
            # Fallback to manual login
            print("[👤] Please login manually in the browser...")
            driver.get(config.LOGIN_URL)
            time.sleep(5)
            
            # Wait for manual login
            login_wait = 300  # 5 minutes
            login_complete = False
            
            for i in range(login_wait):
                current_url = driver.current_url
                if "live/calls" in current_url or "dashboard" in current_url:
                    print("[✅] Manual login successful!")
                    login_complete = True
                    break
                time.sleep(1)
            
            if not login_complete:
                print("[❌] Manual login timeout")
                return
        
        # Navigate to calls page
        print(f"[📞] Opening calls page: {config.CALL_URL}")
        driver.get(config.CALL_URL)
        time.sleep(10)
        
        # Wait for LiveCalls table
        try:
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.ID, "LiveCalls"))
            )
            print("[✅] Active Calls page loaded!")
        except:
            print("[⚠️] LiveCalls table not found, trying to find it...")
            # Try alternative selectors
            try:
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.TAG_NAME, "table"))
                )
                print("[✅] Found a table, continuing...")
            except:
                print("[❌] No table found, but continuing anyway...")
        
        print("[🚀] Real-time monitoring started...")
        
        error_count = 0
        last_refresh = datetime.now()
        next_refresh_interval = get_next_refresh_time()
        
        while error_count < config.MAX_ERRORS:
            try:
                # Dynamic refresh based on the specified pattern
                current_time = datetime.now()
                if (current_time - last_refresh).total_seconds() > next_refresh_interval:
                    print(f"[🔄] Scheduled refresh triggered after {next_refresh_interval} seconds")
                    
                    if refresh_with_cookies(driver):
                        # Wait for LiveCalls table
                        try:
                            WebDriverWait(driver, 30).until(
                                EC.presence_of_element_located((By.ID, "LiveCalls"))
                            )
                            last_refresh = current_time
                            next_refresh_interval = get_next_refresh_time()
                            print(f"[✅] Page refreshed successfully at {current_time.strftime('%H:%M:%S')}")
                        except:
                            print("[⚠️] LiveCalls table not loaded after refresh, but continuing...")
                            last_refresh = current_time
                            next_refresh_interval = get_next_refresh_time()
                    else:
                        print("[❌] Page refresh failed")
                        next_refresh_interval = REFRESH_PATTERN[0]  # Use first interval on failure
                
                # Check if still logged in
                if not check_login_status(driver):
                    print("[⚠️] Session expired, attempting to re-login with cookies...")
                    if not login_with_cookies(driver):
                        print("[❌] Re-login failed")
                        error_count += 1
                        time.sleep(10)
                        continue
                
                # Extract calls
                extract_calls(driver)
                
                error_count = 0
                time.sleep(config.CHECK_INTERVAL)
                
            except KeyboardInterrupt:
                print("\n[🛑] Stopped by user")
                break
            except Exception as e:
                error_count += 1
                print(f"[❌] Main loop error ({error_count}/{config.MAX_ERRORS}): {e}")
                time.sleep(5)
                
    except Exception as e:
        print(f"[💥] Fatal error: {e}")
    finally:
        if driver:
            print("[👋] Closing browser...")
            driver.quit()
    
    print("[*] Monitoring stopped")

if __name__ == "__main__":
    main()
