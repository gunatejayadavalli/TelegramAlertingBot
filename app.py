import re,json,logging
from telethon import TelegramClient, events
from collections import deque

CONFIG_PATH = "config.json"

def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

def save_config(config):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)

config = load_config()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("alertbotlogs.log"),
        logging.StreamHandler()
    ]
)

user = TelegramClient(config["user_session_name"], config["api_id"], config["api_hash"])
bot = TelegramClient(config["bot_session_name"], config["api_id"], config["api_hash"]).start(bot_token=config["bot_token"])

recent_message_ids = deque(maxlen=1000)

async def notify(message, parse_mode=None):
    await bot.send_message(config['destination_channel'], message, parse_mode=parse_mode)

@bot.on(events.NewMessage)
async def handle_commands(event):
    command_text = event.message.message
    sender = await event.get_sender()
    if sender.id not in config['admins']:
        logging.info("You are not authorized to use this bot.")
        await event.reply("You are not authorized to use this bot.")
    else:
        if command_text.startswith('/start'):
            config['is_running'] = True
            save_config(config)
            logging.info("Bot service started.")
            await event.reply("Bot service started.")

        elif command_text.startswith('/stop'):
            config['is_running'] = False
            save_config(config)
            logging.info("Bot service stopped.")
            await event.reply("Bot service stopped.")

        elif command_text.startswith('/setchannels'):
            if config['is_running']:
                channel_usernames = command_text.split()[1:]
                if len(channel_usernames) > 0:
                    config['source_channel_names'] = channel_usernames
                    config['source_channels'] = []
                    save_config(config)
                    for username in channel_usernames:
                        try:
                            entity = await bot.get_entity(username)
                            config['source_channels'].append(entity.id)
                            save_config(config)
                            logging.info(f"Resolved {username} to chat_id {entity.id}")
                        except Exception as e:
                            logging.error(f"Failed to resolve {username}: {e}")
                            await event.reply(f"Failed to resolve {username}: {e}")

                    logging.info(f"Monitoring channels: {', '.join(channel_usernames)}")
                    await event.reply(f"Monitoring channels: {', '.join(channel_usernames)}")
                else:
                    logging.error("Channels list is empty. Please resend the channels list in the format /setchannels <channel1> <channel2>")
                    await event.reply("Channels list is empty. Please resend the channels list in the format <b>/setchannels '&lt;channel1&gt;' '&lt;channel2&gt;'</b>", parse_mode='HTML')
            else:
                logging.error("Please start the bot service using /start.")
                await event.reply("Please start the bot service using /start.")

        elif command_text.startswith('/setkeywords'):
            if config['is_running'] and len(config['source_channels']) > 0:
                keywords = re.findall(r"'(.*?)'", command_text)
                if len(keywords) > 0:
                    config['keywords'] = keywords
                    save_config(config)
                    logging.info(f"Searching for keywords: {', '.join(config['keywords'])}")
                    await event.reply(f"Searching for keywords: {', '.join(config['keywords'])}")
                else:
                    logging.error("Keywords list is empty. Please resend the keywords list in the format /setkeywords '<keyword1>' '<keyword2>'")
                    await event.reply("Keywords list is empty. Please resend the keywords list in the format <b>/setkeywords '&lt;keyword1&gt;' '&lt;keyword2&gt;'</b>", parse_mode='HTML')

            elif not config['is_running']:
                logging.error("Please start the bot service first using /start.")
                await event.reply("Please start the bot service first using /start.")
            elif config['is_running'] and len(config['source_channels']) == 0:
                logging.error("Please set the monitoring channels first using /setchannels.")
                await event.reply("Please set the monitoring channels first using /setchannels.")

        elif command_text.startswith('/clear'):
            config['source_channels'].clear()
            config['source_channel_names'].clear()
            config['keywords'].clear()
            save_config(config)
            logging.info("Cleared all monitored channels and keywords.")
            await event.reply("Cleared all monitored channels and keywords.")

        elif command_text.startswith('/show'):
            channels_list = ', '.join(config['source_channel_names']) if config['source_channel_names'] else "No channels set."
            keywords_list = ', '.join(config['keywords']) if config['keywords'] else "No keywords set."
            logging.info(f"Channels: {channels_list}\nKeywords: {keywords_list}")
            await event.reply(f"Channels: {channels_list}\nKeywords: {keywords_list}")

        elif command_text.startswith('/status'):
            if config['is_running']:
                logging.info("Bot is running.")
                await event.reply("Bot is running.")
            else:
                logging.info("Bot is not running.")
                await event.reply("Bot is not running.")

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

def wildcard_to_regex(pattern):
    parts = pattern.split("*")
    regex_parts = [re.escape(c) + "+" for c in parts if c]
    return ".*?".join(regex_parts)

@user.on(events.NewMessage())
async def handler(event):
    if not config['is_running']:
        return
    channel_id = getattr(event.message.peer_id, 'channel_id', None)
    if channel_id not in config['source_channels']:
        return
    if event.message.id in recent_message_ids:
        return
    recent_message_ids.append(event.message.id)
    message = getattr(event.message, "message", "")
    if not message:
        return
    logging.info(f'Message received from monitored channel: {message}')
    matched_keywords = []
    for kw in config["keywords"]:
        if "&&" in kw:
            if is_pairwise_match(kw, message):
                matched_keywords.append(kw)
        else:
            regex = wildcard_to_regex(kw.upper())
            if re.search(regex, message.upper()):
                matched_keywords.append(kw)
    if matched_keywords:
        logging.info(f'Keywords matched: {matched_keywords}. Forwarding message...')
        try:
            await bot.forward_messages(config['destination_channel'], event.message)
        except Exception as e:
            logging.error(f"Forwarding failed for message from {channel_id}: {e}")
            await notify(f"Forwarding failed for message from {channel_id}: {e}")

async def main():
    await user.start()
    logging.info("Bot is running...")
    try:
        await user.run_until_disconnected()
    except Exception as e:
        logging.error(f"An error occurred: {e}")
        await notify(f"Error: {e}")
    finally:
        logging.info("Bot is shutting down.")
        await notify("Bot is shutting down.")

with user:
    user.loop.run_until_complete(main())