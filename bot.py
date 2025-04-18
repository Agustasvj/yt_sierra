import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes
import httpx
import json

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.DEBUG
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
API_URL = os.environ.get("API_URL", "https://yt-dl-api.onrender.com/download")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send me a YouTube URL, fucker.")

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    if url.startswith("/"):  # Skip commands
        return
    logger.debug(f"Got URL from user {update.effective_user.id}: {url}")
    keyboard = [
        [InlineKeyboardButton("MP4", callback_data=f"mp4_{url}"),
         InlineKeyboardButton("MP3", callback_data=f"mp3_{url}")],
        [InlineKeyboardButton("Audio Only (M4A)", callback_data=f"mp4_audio_{url}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Pick your poison:", reply_markup=reply_markup)

async def handle_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split("_", 1)
    format_type, url = data[0], data[1]

    if format_type == "mp4":
        keyboard = [
            [InlineKeyboardButton("360p", callback_data=f"mp4_360_{url}"),
             InlineKeyboardButton("720p", callback_data=f"mp4_720_{url}"),
             InlineKeyboardButton("1080p", callback_data=f"mp4_1080_{url}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Pick quality:", reply_markup=reply_markup)
    elif format_type == "mp3":
        keyboard = [
            [InlineKeyboardButton("64k", callback_data=f"mp3_64_{url}"),
             InlineKeyboardButton("128k", callback_data=f"mp3_128_{url}"),
             InlineKeyboardButton("192k", callback_data=f"mp3_192_{url}")],
            [InlineKeyboardButton("256k", callback_data=f"mp3_256_{url}"),
             InlineKeyboardButton("320k", callback_data=f"mp3_320_{url}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Pick bitrate:", reply_markup=reply_markup)
    else:  # mp4_audio
        await download_and_send(query, context, url, "mp4_audio")

async def download_and_send(query: Update, context: ContextTypes.DEFAULT_TYPE, url: str, format: str):
    logger.debug(f"Downloading for user {query.from_user.id}: URL={url}, Format={format}")
    await query.edit_message_text(f"Ripping {format}... Hold tight, fucker.")
    async with httpx.AsyncClient(timeout=120.0) as client:
        payload = {"url": url, "format": format}
        logger.debug(f"Sending request to {API_URL} with payload: {payload}")
        try:
            response = await client.post(API_URL, json=payload)
            logger.debug(f"API response status: {response.status_code}, headers: {response.headers}")
            response.raise_for_status()
        except httpx.RequestError as e:
            logger.error(f"API request fucked up: {str(e)}")
            await query.edit_message_text(f"API call fucked up: {str(e)}")
            return
        if response.status_code != 200:
            logger.error(f"API returned shit: {response.status_code} - {response.text}")
            await query.edit_message_text(f"API fucked up: {response.text}")
            return
        file_data = response.content
        filename = response.headers.get("Content-Disposition", "attachment; filename=download").split("filename=")[1].strip('"')
        metadata = json.loads(response.headers.get("X-Metadata", "{}"))
        caption = f"{metadata.get('title', 'Unknown')}\nBy: {metadata.get('uploader', 'Unknown')}"
        logger.debug(f"Sending file: {filename}, size: {len(file_data)} bytes")
    try:
        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=file_data,
            filename=filename,
            caption=caption
        )
        logger.debug("File sent to Telegram")
    except Exception as e:
        logger.error(f"Telegram send fucked up: {str(e)}")
        await query.edit_message_text(f"Send fucked up: {str(e)}")
    await query.delete_message()

async def run_bot():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set. Get your shit together.")
        raise ValueError("BOT_TOKEN not set")
    logger.info("Starting Telegram bot")
    # Clear webhook
    async with httpx.AsyncClient() as client:
        await client.get(f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url=")
    logger.info("Webhook cleared")
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(None, handle_url))
    application.add_handler(CallbackQueryHandler(handle_format, pattern="^(mp4|mp3|mp4_audio)_"))
    application.add_handler(CallbackQueryHandler(download_and_send, pattern="^(mp4_360|mp4_720|mp4_1080|mp3_64|mp3_128|mp3_192|mp3_256|mp3_320)_"))
    logger.info("Bot polling started")
    await application.initialize()
    await application.start()
    await application.updater.start_polling(timeout=10, drop_pending_updates=True)
    logger.info("Bot is running")
    # Keep alive
    while True:
        await asyncio.sleep(3600)  # Sleep 1hr, Render kills idle after 15min

if __name__ == "__main__":
    asyncio.run(run_bot())