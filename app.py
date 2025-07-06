import os
import re
import json
import logging
import asyncio
from telethon import TelegramClient, events
from collections import deque
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_NAME = os.getenv("SESSION_NAME", "user_session")
DESTINATION_CHANNEL = os.getenv("DESTINATION_CHANNEL")
CONTROL_GROUP = os.getenv("CONTROL_GROUP")
LOG_PATH = os.getenv("TELEGRAM_ALERTING_BOT_LOG", "./alertbotlogs.log")
CONFIG_PATH = os.getenv("TELEGRAM_ALERTING_BOT_CONFIG_PATH", "./config.json")

# Logging setup
logging.basicConfig(filename=LOG_PATH, level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s')

config_lock = asyncio.Lock()
recent_message_ids = deque(maxlen=1000)

def load_config():
    if not os.path.exists(CONFIG_PATH):
        return {"is_running": True, "source_channels": [], "source_channel_names": [], "keywords": []}
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

async def save_config(config):
    async with config_lock:
        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=2)

config = load_config()
client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

def wildcard_to_regex(pattern):
    parts = pattern.split("*")
    regex_parts = [re.escape(c) + "+" for c in parts if c]
    return ".*?".join(regex_parts)

def is_pairwise_match(pattern, message):
    pairs = pattern.split("&&")
    idx = 0
    msg = message.upper()
    for pair in pairs:
        if len(pair) != 2:
            return False
        found = False
        while idx < len(msg) - 1:
            if msg[idx] == pair[0] and msg[idx + 1] == pair[1]:
                found = True
                break
            idx += 1
        if not found:
            return False
        idx += 1
    return True

async def register_command_handler(control_group_entity):
    @client.on(events.NewMessage(chats=control_group_entity, pattern='/'))
    async def command_handler(event):
        cmd = event.message.message.strip()

        if cmd.startswith("/start"):
            config["is_running"] = True
            await save_config(config)
            await event.reply("✅ Bot monitoring started.")

        elif cmd.startswith("/stop"):
            config["is_running"] = False
            await save_config(config)
            await event.reply("🛑 Bot monitoring stopped.")

        elif cmd.startswith("/setchannels"):
            channel_usernames = cmd.split()[1:]
            config["source_channel_names"] = channel_usernames
            config["source_channels"] = []
            for username in channel_usernames:
                try:
                    entity = await client.get_entity(username)
                    config["source_channels"].append(entity.id)
                    logging.info(f"Resolved {username} to {entity.id}")
                except Exception as e:
                    await event.reply(f"❌ Failed to resolve {username}: {e}")
            await save_config(config)
            await event.reply(f"📡 Monitoring: {', '.join(channel_usernames)}")

        elif cmd.startswith("/setkeywords"):
            keywords = re.findall(r"""['"](.+?)['"]""", cmd)
            if not keywords:
                await event.reply("❌ No keywords detected. Use quotes like 'KEY1' or \"KEY1\".")
                return
            config["keywords"] = keywords
            await save_config(config)
            await event.reply(f"🔍 Keywords set: {', '.join(keywords)}")

        elif cmd.startswith("/clear"):
            config["source_channels"] = []
            config["source_channel_names"] = []
            config["keywords"] = []
            await save_config(config)
            await event.reply("🧹 Cleared channels and keywords.")

        elif cmd.startswith("/show"):
            channels = ", ".join(config["source_channel_names"]) or "None"
            keywords = ", ".join(config["keywords"]) or "None"
            await event.reply(f"📋 Channels: {channels}\n🔍 Keywords: {keywords}")

        elif cmd.startswith("/status"):
            status = "🟢 Running" if config["is_running"] else "🔴 Stopped"
            await event.reply(f"📡 Status: {status}")

@client.on(events.NewMessage())
async def monitor_handler(event):
    if not config["is_running"]:
        return
    channel_id = getattr(event.message.peer_id, 'channel_id', None)
    if channel_id not in config["source_channels"]:
        return
    if event.message.id in recent_message_ids:
        return
    recent_message_ids.append(event.message.id)
    message = event.message.message or ""
    matched = False
    for kw in config["keywords"]:
        if "&&" in kw:
            if is_pairwise_match(kw, message):
                matched = True
                break
        else:
            regex = wildcard_to_regex(kw.upper())
            if re.search(regex, message.upper()):
                matched = True
                break
    if matched:
        logging.info(f"✅ Keyword match found. Forwarding message: {message[:60]}...")
        try:
            await client.forward_messages(DESTINATION_CHANNEL, event.message)
        except Exception as e:
            logging.error(f"⚠️ Forwarding failed: {e}")

async def main():
    await client.start()
    logging.info("🔄 Client started...")

    # Convert control group to integer ID if needed
    try:
        control_group_id = int(CONTROL_GROUP)
    except ValueError:
        control_group_id = CONTROL_GROUP

    control_group_entity = await client.get_input_entity(control_group_id)
    await register_command_handler(control_group_entity)

    print("✅ AlertBot is online.")
    logging.info("✅ AlertBot is online.")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())