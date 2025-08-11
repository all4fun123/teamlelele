import os
import sys
import io
import time
import json
import random
import asyncio
import aiohttp
import hashlib
import logging
import threading
from datetime import datetime
from pytz import timezone
from flask import Flask

# ==== Flask app để Render detect port ====
app = Flask(__name__)

@app.route("/")
def home():
    return "Script đang chạy nền OK!"

# Force UTF-8 encoding for console output
if sys.platform.startswith('win'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Set up logging to console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger()

# Class to store account state
class AccountState:
    def __init__(self):
        self.is_first_run = True
        self.account_nick = None
        self.provinces = []
        self.share_count = 0
        self.max_shares = 999999999

async def run_event_flow(session, username, bearer_token, state):
    try:
        maker_code = "BEAuSN19"
        backend_key_sign = "de54c591d457ed1f1769dda0013c9d30f6fc9bbff0b36ea0a425233bd82a1a22"
        login_url = "https://apiwebevent.vtcgame.vn/besnau19home/Event"
        au_url = "https://au.vtc.vn"

        def get_current_timestamp():
            return int(time.time())

        def sha256_hex(data):
            return hashlib.sha256(data.encode('utf-8')).hexdigest()

        async def generate_sign(time_value, func):
            raw = f"{time_value}{maker_code}{func}{backend_key_sign}"
            return sha256_hex(raw)

        browser_headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Referer": au_url
        }

        mission_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Authorization": bearer_token
        }

        async def send_wish(session, account_nick, state):
            if not state.provinces:
                logger.info(f"{account_nick}: Đang lấy danh sách tỉnh...")
                get_list_time = get_current_timestamp()
                get_list_sign = await generate_sign(get_list_time, "wish-get-list")
                list_payload = {
                    "time": get_list_time,
                    "fromIP": "",
                    "sign": get_list_sign,
                    "makerCode": maker_code,
                    "func": "wish-get-list",
                    "data": ""
                }
                async with session.post(login_url, json=list_payload, headers=mission_headers) as response:
                    list_res = await response.json()

                if list_res.get("code") != 1:
                    logger.warning(f"{account_nick}: Lấy danh sách tỉnh thất bại.")
                    return None

                state.provinces = list_res["data"]["list"]
                logger.info(f"{account_nick}: Lấy danh sách {len(state.provinces)} tỉnh thành công.")

            selected = random.choice(state.provinces)
            logger.info(f"{account_nick}: Chọn tỉnh {selected['ProvinceName']}")
            wish_time = get_current_timestamp()
            wish_sign = await generate_sign(wish_time, "wish-send")
            wish_payload = {
                "time": wish_time,
                "fromIP": "",
                "sign": wish_sign,
                "makerCode": maker_code,
                "func": "wish-send",
                "data": {
                    "FullName": account_nick,
                    "Avatar": selected["Avatar"],
                    "ProvinceID": selected["ProvinceID"],
                    "ProvinceName": selected["ProvinceName"],
                    "Content": "Chúc sự kiện thành công!"
                }
            }
            async with session.post(login_url, json=wish_payload, headers=mission_headers) as response:
                wish_res = await response.json()

            if wish_res.get("mess") != "Gửi lời chúc thành công!":
                logger.warning(f"{account_nick}: Gửi lời chúc thất bại: {wish_res.get('mess')}")
                return None

            log_id = wish_res["code"]
            logger.info(f"{account_nick}: Gửi lời chúc thành công - LogID: {log_id}")
            return log_id

        async def perform_share(session, log_id, account_nick, username):
            logger.info(f"{account_nick}: Đang lấy token share...")
            share_time = get_current_timestamp()
            share_raw = f"{share_time}{maker_code}{au_url}{backend_key_sign}"
            share_sign = sha256_hex(share_raw)
            share_url = f"{au_url}/bsau/api/generate-share-token?username={username}&time={share_time}&sign={share_sign}"
            async with session.get(share_url, headers={"User-Agent": browser_headers["User-Agent"]}) as response:
                content_type = response.headers.get('Content-Type', '')
                response_text = await response.text()
                if 'application/json' not in content_type:
                    logger.warning(f"{account_nick}: Không nhận JSON khi lấy token")
                    return False
                try:
                    share_res = json.loads(response_text)
                except json.JSONDecodeError:
                    logger.warning(f"{account_nick}: JSON lỗi: {response_text}")
                    return False
                share_token = share_res.get("token")
                if not share_token:
                    logger.warning(f"{account_nick}: Token share trống")
                    return False
                logger.info(f"{account_nick}: Token share: {share_token}")

            final_time = get_current_timestamp()
            final_sign = await generate_sign(final_time, "wish-share")
            share_payload = {
                "time": final_time,
                "fromIP": "",
                "sign": final_sign,
                "makerCode": maker_code,
                "func": "wish-share",
                "data": {
                    "LogID": log_id,
                    "key": share_token,
                    "timestamp": final_time,
                    "a": "aa"
                }
            }
            async with session.post(login_url, json=share_payload, headers=mission_headers) as response:
                share_send_res = await response.json()
                if share_send_res.get("code") == 1:
                    logger.info(f"{account_nick}: Share thành công!")
                    return True
                else:
                    logger.warning(f"{account_nick}: Share thất bại: {share_send_res.get('mess')}")
                    return False

        if state.is_first_run:
            logger.info(f"{username}: Đăng nhập lần đầu...")
            login_time = get_current_timestamp()
            login_sign = await generate_sign(login_time, "account-login")
            login_payload = {
                "time": login_time,
                "fromIP": "",
                "sign": login_sign,
                "makerCode": maker_code,
                "func": "account-login",
                "data": ""
            }
            async with session.post(login_url, json=login_payload, headers=mission_headers) as response:
                login_res = await response.json()
                if login_res.get("code") != 1:
                    raise Exception(f"{username}: Đăng nhập thất bại: {login_res.get('mess')}")
                state.account_nick = login_res['data']['AccountNick']
                logger.info(f"{username}: Đăng nhập thành công: {state.account_nick}")
            state.is_first_run = False

        if not state.account_nick:
            raise Exception(f"{username}: Không có thông tin đăng nhập.")

        if state.share_count >= state.max_shares:
            logger.info(f"{username}: Đạt giới hạn share ({state.share_count}/{state.max_shares})")
            return False

        while True:
            log_id = await send_wish(session, state.account_nick, state)
            if log_id:
                if await perform_share(session, log_id, state.account_nick, username):
                    state.share_count += 1
                    return True
                else:
                    await asyncio.sleep(5)
                    continue
            else:
                await asyncio.sleep(5)
                continue

    except Exception as err:
        logger.error(f"{username}: Lỗi: {str(err)}")
        return False

async def load_accounts():
    accounts = []
    try:
        with open('accounts.txt', 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    username, token = line.split('|')
                    accounts.append((username, f"Bearer {token}"))
        return accounts
    except Exception as err:
        logger.error(f"Lỗi đọc file accounts.txt: {str(err)}")
        return []

async def main():
    accounts = await load_accounts()
    if not accounts:
        logger.error("Không có tài khoản nào")
        return
    async with aiohttp.ClientSession() as session:
        states = {username: AccountState() for username, _ in accounts}
        semaphore = asyncio.Semaphore(5)
        async def process_account(username, bearer_token, state):
            async with semaphore:
                success = await run_event_flow(session, username, bearer_token, state)
                if success:
                    await asyncio.sleep(5)
                else:
                    await asyncio.sleep(5)
                return success

        while True:
            tasks = [process_account(username, bearer_token, states[username])
                     for username, bearer_token in accounts]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            if all(isinstance(result, Exception) or result is False for result in results):
                await asyncio.sleep(60)
            else:
                await asyncio.sleep(1)

# ==== Hàm chạy nền ====
def run_background():
    asyncio.run(main())

if __name__ == "__main__":
    t = threading.Thread(target=run_background, daemon=True)
    t.start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
