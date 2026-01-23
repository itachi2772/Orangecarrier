import time
import re
import requests
import os
import random
import json
from datetime import datetime, timedelta
from seleniumbase import SB
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException, NoSuchElementException
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

def solve_cloudflare_captcha_advanced(driver):
    """Advanced CloudFlare CAPTCHA solver with multiple approaches"""
    try:
        print("[🛡️] Advanced CloudFlare CAPTCHA solver activated...")
        
        # Approach 1: Try to find and click the CAPTCHA iframe
        try:
            captcha_iframe = WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 
                    "iframe[src*='challenges.cloudflare.com'], iframe[title*='challenge'], iframe[src*='recaptcha']"))
            )
            
            if captcha_iframe:
                print("[🔍] CAPTCHA iframe found, attempting auto-completion...")
                driver.switch_to.frame(captcha_iframe)
                
                # Try different CAPTCHA checkbox selectors
                checkbox_selectors = [
                    "input[type='checkbox']",
                    ".recaptcha-checkbox-border",
                    "#recaptcha-anchor",
                    ".cf-challenge-checkbox",
                    ".h-captcha",
                    ".checkbox"
                ]
                
                for selector in checkbox_selectors:
                    try:
                        checkbox = WebDriverWait(driver, 3).until(
                            EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                        )
                        if checkbox:
                            print(f"[✅] CAPTCHA checkbox found with selector: {selector}")
                            
                            # Human-like behavior before clicking
                            human_like_delay(2, 4)
                            
                            # Advanced mouse movement simulation
                            human_like_mouse_movement(driver, checkbox)
                            
                            print("[👆] CAPTCHA checkbox clicked, waiting for verification...")
                            
                            # Wait for verification process
                            human_like_delay(8, 12)
                            
                            # Check if verification is complete
                            try:
                                verified_indicator = driver.find_element(By.CSS_SELECTOR, ".recaptcha-checkbox-checked, .cf-challenge-success")
                                if verified_indicator:
                                    print("[🎉] CAPTCHA verification completed automatically!")
                                    driver.switch_to.default_content()
                                    return True
                            except:
                                pass
                            
                            break
                    except:
                        continue
                
                driver.switch_to.default_content()
                
        except TimeoutException:
            print("[⏱️] No CAPTCHA iframe found with first approach")
            driver.switch_to.default_content()
        
        # Approach 2: Look for challenge form and submit
        try:
            challenge_form = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "form[action*='challenge'], .challenge-form"))
            )
            
            if challenge_form:
                print("[🔍] Challenge form found, looking for submit button...")
                
                submit_selectors = [
                    "input[type='submit']",
                    "button[type='submit']",
                    ".btn-success",
                    ".button--success",
                    "[type='submit']"
                ]
                
                for selector in submit_selectors:
                    try:
                        submit_btn = challenge_form.find_element(By.CSS_SELECTOR, selector)
                        if submit_btn and submit_btn.is_enabled():
                            human_like_delay(2, 3)
                            human_like_mouse_movement(driver, submit_btn)
                            print("[✅] Challenge form submitted")
                            human_like_delay(5, 8)
                            return True
                    except:
                        continue
                        
        except TimeoutException:
            print("[⏱️] No challenge form found")
        
        # Approach 3: Direct CAPTCHA element detection
        captcha_elements = driver.find_elements(By.CSS_SELECTOR, 
            ".cf-captcha, .captcha, .hcaptcha, .g-recaptcha, [data-sitekey]")
        
        if captcha_elements:
            print(f"[🔍] Found {len(captcha_elements)} CAPTCHA elements, attempting interaction...")
            
            for element in captcha_elements:
                try:
                    if element.is_displayed() and element.is_enabled():
                        human_like_delay(1, 2)
                        driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", element)
                        human_like_delay(1, 2)
                        human_like_mouse_movement(driver, element)
                        print("[👆] CAPTCHA element clicked")
                        human_like_delay(6, 10)
                        return True
                except:
                    continue
        
        print("[❌] CAPTCHA auto-completion failed with all approaches")
        return False
        
    except Exception as e:
        print(f"[💥] Advanced CAPTCHA solver error: {e}")
        driver.switch_to.default_content()
        return False

def check_and_solve_captcha(driver):
    """Check for CAPTCHA and attempt to solve it with enhanced detection"""
    try:
        # Enhanced CAPTCHA indicators
        captcha_indicators = [
            "challenges.cloudflare.com",
            "cf-challenge", 
            "recaptcha",
            "hcaptcha",
            "Just a moment",
            "Checking your browser",
            "Verifying you are human",
            "Challenge",
            "Security check"
        ]
        
        page_source = driver.page_source.lower()
        current_url = driver.current_url.lower()
        page_title = driver.title.lower()
        
        for indicator in captcha_indicators:
            indicator_lower = indicator.lower()
            if (indicator_lower in page_source or 
                indicator_lower in current_url or 
                indicator_lower in page_title):
                print(f"[🛡️] CAPTCHA detected: {indicator}")
                return solve_cloudflare_captcha_advanced(driver)
        
        # Additional check for CAPTCHA elements in DOM
        captcha_selectors = [
            ".cf-captcha",
            ".captcha", 
            ".hcaptcha",
            ".g-recaptcha",
            "[data-sitekey]",
            "iframe[src*='captcha']",
            "iframe[src*='challenge']"
        ]
        
        for selector in captcha_selectors:
            try:
                if driver.find_elements(By.CSS_SELECTOR, selector):
                    print(f"[🔍] CAPTCHA element found with selector: {selector}")
                    return solve_cloudflare_captcha_advanced(driver)
            except:
                continue
                
        return False
        
    except Exception as e:
        print(f"[❌] Error checking CAPTCHA: {e}")
        return False

def safe_refresh_with_advanced_captcha(driver):
    """Safe page refresh with advanced CAPTCHA handling"""
    max_retries = 2
    retry_count = 0
    
    while retry_count <= max_retries:
        try:
            print(f"[🔄] Refreshing page... (Attempt {retry_count + 1})")
            driver.refresh()
            human_like_delay(3, 5)
            
            # Wait for page to load
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            # Check for CAPTCHA immediately after refresh
            human_like_delay(2, 4)
            
            if check_and_solve_captcha(driver):
                print("[✅] CAPTCHA auto-completed successfully")
                human_like_delay(5, 8)  # Extra time for CAPTCHA processing
                
                # Verify we're past CAPTCHA by checking for main content
                try:
                    WebDriverWait(driver, 15).until(
                        EC.presence_of_element_located((By.ID, "LiveCalls"))
                    )
                    print("[✅] Successfully bypassed CAPTCHA and loaded main content")
                    return True
                except TimeoutException:
                    print("[⚠️] Main content not loaded after CAPTCHA, might need retry")
                    retry_count += 1
                    continue
            else:
                # No CAPTCHA found, verify main content is loaded
                try:
                    WebDriverWait(driver, 15).until(
                        EC.presence_of_element_located((By.ID, "LiveCalls"))
                    )
                    print("[✅] Page refreshed successfully without CAPTCHA")
                    return True
                except TimeoutException:
                    print("[⚠️] Main content not loaded, might have hidden CAPTCHA")
                    retry_count += 1
                    continue
                    
        except Exception as e:
            print(f"[❌] Refresh attempt {retry_count + 1} failed: {e}")
            retry_count += 1
            human_like_delay(5, 10)
    
    print("[💥] All refresh attempts failed")
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

def handle_captcha_protection(sb, url, step_name):
    """Handle CAPTCHA protection with advanced auto-solving"""
    print(f"🛡️ CAPTCHA protection check for {step_name}...")
    
    try:
        # Open in UC mode
        sb.driver.uc_open_with_reconnect(url, reconnect_time=3)
        human_like_delay(2, 4)
        
        # Advanced CAPTCHA check and solve
        if check_and_solve_captcha(sb.driver):
            print(f"✅ CAPTCHA auto-completion successful for {step_name}")
        else:
            # Fallback to manual click with enhanced detection
            print(f"[🔧] Using enhanced fallback CAPTCHA handling for {step_name}")
            try:
                sb.uc_gui_click_captcha()
            except:
                print("[⚠️] Manual CAPTCHA click failed, continuing...")
        
        human_like_delay(3, 5)
        return True
        
    except Exception as e:
        print(f"[❌] CAPTCHA handling error for {step_name}: {e}")
        return False

def auto_login(driver, email, password):
    """Automatically login to Orange Carrier"""
    try:
        print(f"[🔐] Attempting auto-login for: {email}")
        
        # Navigate to login page
        driver.get(config.LOGIN_URL)
        human_like_delay(3, 5)
        
        # Check for CAPTCHA first
        if check_and_solve_captcha(driver):
            print("[✅] CAPTCHA solved before login")
        
        # Wait for login form
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='email'], input[name='email'], #email, input[type='text']"))
            )
        except TimeoutException:
            print("[⚠️] Login form not found, checking if already logged in")
            if config.LOGIN_URL not in driver.current_url:
                print("[✅] Already logged in")
                return True
        
        # Find email field
        email_selectors = [
            "input[type='email']",
            "input[name='email']",
            "#email",
            "input[placeholder*='email']",
            "input[placeholder*='Email']",
            ".email-input",
            "[type='email']"
        ]
        
        email_field = None
        for selector in email_selectors:
            try:
                email_field = driver.find_element(By.CSS_SELECTOR, selector)
                if email_field.is_displayed():
                    break
            except:
                continue
        
        if email_field:
            # Enter email with human-like typing
            email_field.clear()
            human_like_delay(0.5, 1)
            for char in email:
                email_field.send_keys(char)
                time.sleep(random.uniform(0.05, 0.15))
            print(f"[📧] Email entered: {email}")
        
        # Find password field
        password_selectors = [
            "input[type='password']",
            "input[name='password']",
            "#password",
            "input[placeholder*='password']",
            "input[placeholder*='Password']",
            ".password-input"
        ]
        
        password_field = None
        for selector in password_selectors:
            try:
                password_field = driver.find_element(By.CSS_SELECTOR, selector)
                if password_field.is_displayed():
                    break
            except:
                continue
        
        if password_field:
            # Enter password
            password_field.clear()
            human_like_delay(0.5, 1)
            for char in password:
                password_field.send_keys(char)
                time.sleep(random.uniform(0.05, 0.15))
            print("[🔑] Password entered")
        else:
            print("[❌] Password field not found")
            return False
        
        # Find submit button
        submit_selectors = [
            "button[type='submit']",
            "input[type='submit']",
            ".login-button",
            ".btn-primary",
            ".btn-login",
            "button[type='button']",
            "button"
        ]
        
        submit_button = None
        for selector in submit_selectors:
            try:
                submit_button = driver.find_element(By.CSS_SELECTOR, selector)
                if submit_button.is_displayed() and submit_button.is_enabled():
                    break
            except:
                continue
        
        if submit_button:
            # Click submit
            human_like_delay(1, 2)
            human_like_mouse_movement(driver, submit_button)
            print("[✅] Login button clicked")
        else:
            # Try pressing Enter
            if password_field:
                password_field.send_keys(Keys.RETURN)
                print("[↵️] Sent Enter key to password field")
        
        # Wait for login to complete
        human_like_delay(5, 8)
        
        # Check if login was successful
        current_url = driver.current_url
        if config.LOGIN_URL not in current_url and "login" not in current_url.lower():
            print("[🎉] Login successful!")
            
            # Wait for dashboard to load
            try:
                WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 
                        "#dashboard, #LiveCalls, .dashboard, .main-content, body"))
                )
                print("[✅] Dashboard loaded successfully")
                return True
            except:
                # Try to navigate to calls page directly
                driver.get(config.CALL_URL)
                human_like_delay(5, 8)
                return True
        else:
            print("[❌] Login failed - still on login page")
            return False
            
    except Exception as e:
        print(f"[💥] Auto-login error: {e}")
        return False

def check_login_status(driver):
    """Check if user is still logged in"""
    try:
        # Check for logout button or user profile
        logout_indicators = [
            "a[href*='logout']",
            "button:contains('Logout')",
            "a:contains('Logout')",
            ".user-profile",
            ".account-menu"
        ]
        
        for selector in logout_indicators:
            try:
                if driver.find_elements(By.CSS_SELECTOR, selector):
                    return True
            except:
                continue
        
        # Check current URL
        if config.LOGIN_URL in driver.current_url:
            return False
        
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

def wait_for_login(sb):
    """Wait for login - try auto-login first, then manual fallback"""
    
    # First try auto-login if credentials are provided
    if hasattr(config, 'ORANGE_EMAIL') and hasattr(config, 'ORANGE_PASSWORD'):
        if config.ORANGE_EMAIL and config.ORANGE_PASSWORD:
            print(f"[🤖] Attempting auto-login for: {config.ORANGE_EMAIL}")
            
            # Navigate to login page with CAPTCHA handling
            handle_captcha_protection(sb, config.LOGIN_URL, "Login Page")
            
            # Try auto-login
            if auto_login(sb.driver, config.ORANGE_EMAIL, config.ORANGE_PASSWORD):
                print("[✅] Auto-login successful!")
                
                # Verify we're on calls page
                handle_captcha_protection(sb, config.CALL_URL, "Calls Page")
                
                try:
                    WebDriverWait(sb.driver, 20).until(
                        EC.presence_of_element_located((By.ID, "LiveCalls"))
                    )
                    return True
                except:
                    # Try to navigate directly
                    sb.driver.get(config.CALL_URL)
                    human_like_delay(5, 8)
                    return True
            else:
                print("[⚠️] Auto-login failed, falling back to manual login")
    
    # Fallback to manual login
    print(f"[👤] Manual login required: {config.LOGIN_URL}")
    handle_captcha_protection(sb, config.LOGIN_URL, "Login Page")
    print("➡️ Please login manually in the browser...")
    
    try:
        WebDriverWait(sb.driver, 300).until(  # 5 minutes timeout
            lambda d: d.current_url.startswith(config.BASE_URL) and 
                     not d.current_url.startswith(config.LOGIN_URL) and
                     "login" not in d.current_url.lower()
        )
        print("✅ Manual login successful!")
        return True
    except TimeoutException:
        print("[❌] Login timeout")
        return False

def main():
    # Detect if running on Heroku
    is_heroku = os.environ.get('DYNO') is not None
    
    # FIXED: Only use parameters that SB() constructor supports
    sb_config = {
        'uc': True,
        'incognito': True,
        'agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        'headless': is_heroku,     # Headless on Heroku
        'headless2': is_heroku,    # Headless2 on Heroku
    }
    
    print(f"[🌍] Running on Heroku: {is_heroku}")
    print(f"[⚙️] SeleniumBase config: {sb_config}")
    
    with SB(**sb_config) as sb:
        try:
            # Increase timeout for Heroku
            sb.driver.set_page_load_timeout(60)
            sb.driver.set_script_timeout(60)
            
            # Set Chrome options for Heroku
            if is_heroku:
                options = sb.driver.options
                options.add_argument('--no-sandbox')
                options.add_argument('--disable-dev-shm-usage')
                options.add_argument('--disable-gpu')
                options.add_argument('--headless')
                options.add_argument('--disable-blink-features=AutomationControlled')
                options.add_experimental_option("excludeSwitches", ["enable-automation"])
                options.add_experimental_option('useAutomationExtension', False)
                print("[⚙️] Chrome options set for Heroku")
            
            if not wait_for_login(sb):
                return
            
            handle_captcha_protection(sb, config.CALL_URL, "Calls Page")
            WebDriverWait(sb.driver, 30).until(EC.presence_of_element_located((By.ID, "LiveCalls")))
            print("✅ Active Calls page loaded!")
            print("[*] Real-time monitoring started...")

            error_count = 0
            last_refresh = datetime.now()
            next_refresh_interval = get_next_refresh_time()
            
            while error_count < config.MAX_ERRORS:
                try:
                    # Dynamic refresh based on the specified pattern
                    current_time = datetime.now()
                    if (current_time - last_refresh).total_seconds() > next_refresh_interval:
                        print(f"[🔄] Scheduled refresh triggered after {next_refresh_interval} seconds")
                        
                        if safe_refresh_with_advanced_captcha(sb.driver):
                            # Wait for LiveCalls table
                            WebDriverWait(sb.driver, 30).until(
                                EC.presence_of_element_located((By.ID, "LiveCalls"))
                            )
                            last_refresh = current_time
                            next_refresh_interval = get_next_refresh_time()
                            print(f"[✅] Page refreshed successfully at {current_time.strftime('%H:%M:%S')}")
                        else:
                            print("[❌] Page refresh failed, trying to recover...")
                            handle_captcha_protection(sb, config.CALL_URL, "Recovery Refresh")
                            next_refresh_interval = REFRESH_PATTERN[0]  # Use first interval on failure
                    
                    # Check if still logged in
                    if config.LOGIN_URL in sb.driver.current_url or not check_login_status(sb.driver):
                        print("[⚠️] Session expired, re-logging in")
                        if not wait_for_login(sb):
                            break
                        handle_captcha_protection(sb, config.CALL_URL, "Re-login Calls Page")
                    
                    # Extract calls
                    extract_calls(sb.driver)
                    
                    error_count = 0
                    time.sleep(config.CHECK_INTERVAL)
                    
                except KeyboardInterrupt:
                    print("\n[🛑] Stopped by user")
                    break
                except Exception as e:
                    error_count += 1
                    print(f"[❌] Main loop error ({error_count}/{config.MAX_ERRORS}): {e}")
                    
                    # Enhanced CAPTCHA-related error handling
                    error_str = str(e).lower()
                    if any(keyword in error_str for keyword in ["captcha", "cloudflare", "challenge", "security", "verification"]):
                        print("[🛡️] CAPTCHA-related error detected, attempting advanced recovery...")
                        handle_captcha_protection(sb, sb.driver.current_url, "Error Recovery")
                        human_like_delay(10, 15)  # Longer delay after CAPTCHA recovery
                    
                    time.sleep(5)
                    
        except Exception as e:
            print(f"[💥] Fatal error: {e}")
    
    print("[*] Monitoring stopped")

if __name__ == "__main__":
    main()
