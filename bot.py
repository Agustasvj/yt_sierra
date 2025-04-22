import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
import httpx
import os
import re
from io import BytesIO
import urllib.parse

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.DEBUG
)
logger = logging.getLogger(__name__)

BOT_TOKEN = "7643200755:AAEnY79hQQ98ovHCmOp-IOcscwvDGqUbEMM"
API_URL = "http://127.0.0.1:8000/download"

def sanitize_filename(filename):
    return re.sub(r'[<>:"/\\|?*]', '', filename).strip()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Yo, I’m SIERRA’s fuckin’ YouTube DL bot. Drop a YouTube URL or song name, and I’ll hook you up."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send a YouTube URL or song name. Pick MP3 for bitrate (64k-320k) or MP4 for quality (360p-1080p), then hit Download."
    )

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    parsed_url = urllib.parse.urlparse(query)

    # Check if it’s a URL
    is_url = bool(parsed_url.scheme and parsed_url.netloc)
    if is_url and not any(
        domain in parsed_url.netloc
        for domain in ["youtube.com", "youtu.be", "m.youtube.com"]
    ):
        await update.message.reply_text("Gimme a real YouTube URL, dipshit.")
        return

    context.user_data["query"] = query
    keyboard = [
        [InlineKeyboardButton("MP3", callback_data="format_mp3"), InlineKeyboardButton("MP4", callback_data="format_mp4")]
    ]
    await update.message.reply_text("Pick a format:", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    logger.debug(f"Button click from {user_id}: {query.data}")

    if query.data == "format_mp3":
        context.user_data["format"] = "mp3"
        keyboard = [
            [InlineKeyboardButton("64kbps", callback_data="bitrate_64"), InlineKeyboardButton("128kbps", callback_data="bitrate_128"), InlineKeyboardButton("192kbps", callback_data="bitrate_192")],
            [InlineKeyboardButton("256kbps", callback_data="bitrate_256"), InlineKeyboardButton("320kbps", callback_data="bitrate_320")]
        ]
        await query.message.edit_text("Pick a bitrate for MP3:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "format_mp4":
        context.user_data["format"] = "mp4"
        keyboard = [
            [InlineKeyboardButton("360p", callback_data="quality_360"), InlineKeyboardButton("720p", callback_data="quality_720"), InlineKeyboardButton("1080p", callback_data="quality_1080")]
        ]
        await query.message.edit_text("Pick a quality for MP4:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("bitrate_"):
        bitrate = query.data.split("_")[1]
        context.user_data["bitrate"] = bitrate
        context.user_data["quality"] = None
        keyboard = [[InlineKeyboardButton("Download", callback_data="download")]]
        await query.message.edit_text(f"Ready to rip MP3 at {bitrate}kbps. Hit Download:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("quality_"):
        quality = query.data.split("_")[1]
        context.user_data["quality"] = quality
        context.user_data["bitrate"] = None
        keyboard = [[InlineKeyboardButton("Download", callback_data="download")]]
        await query.message.edit_text(f"Ready to rip MP4 at {quality}p. Hit Download:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "download":
        search_query = context.user_data.get("query")
        format_type = context.user_data.get("format")
        bitrate = context.user_data.get("bitrate")
        quality = context.user_data.get("quality")

        if not search_query or not format_type:
            await query.message.edit_text("Shit’s fucked, start over with a URL or song name.")
            return

        final_format = f"mp3_{bitrate}" if format_type == "mp3" and bitrate else f"mp4_{quality}" if format_type == "mp4" and quality else None
        if not final_format:
            await query.message.edit_text("Format’s fucked, try again.")
            return

        logger.debug(f"Downloading for user {user_id}: Query={search_query}, Format={final_format}")
        processing_msg = await query.message.reply_text(f"Ripping {final_format.upper()} for ‘{search_query}’… Starting…")
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                request_data = {"url": search_query, "format": final_format}
                logger.debug(f"Sending request: {request_data}")
                response = await client.post(API_URL, json=request_data, timeout=None)
                logger.debug(f"API response status: {response.status_code}")
                response.raise_for_status()

                await processing_msg.edit_text(f"Ripping {final_format.upper()}… Processing…")
                metadata = eval(response.headers.get("X-Metadata", "{}"))
                title = sanitize_filename(metadata.get("title", "Unknown_Video"))
                file_ext = "mp4" if final_format.startswith("mp4_") else "mp3"
                file_name = f"{title}.{file_ext}"

                # Send thumbnail
                thumbnail = metadata.get("thumbnail")
                if thumbnail and os.path.exists(thumbnail):
                    await processing_msg.edit_text(f"Ripping {final_format.upper()}… Sending cover photo…")
                    with open(thumbnail, "rb") as thumb:
                        await query.message.reply_photo(
                            photo=thumb,
                            caption=f"Cover for {metadata.get('title', 'Unknown')}"
                        )

                file_size = len(response.content) / (1024 * 1024)  # MB
                if file_size < 50:
                    await processing_msg.edit_text(f"Ripping {final_format.upper()}… Uploading to Telegram…")
                    await query.message.reply_document(
                        document=BytesIO(response.content),
                        filename=file_name,
                        caption=f"Got your shit:\nTitle: {metadata.get('title', 'Unknown')}\nUploader: {metadata.get('uploader', 'Unknown')}\nDuration: {metadata.get('duration', 0)}s"
                    )
                    await query.message.delete()
                    await processing_msg.delete()
                else:
                    await processing_msg.edit_text(
                        f"File’s too fuckin’ big ({file_size:.1f}MB). Grab it manually or host the API publicly.\n"
                        f"Title: {metadata.get('title', 'Unknown')}\nUploader: {metadata.get('uploader', 'Unknown')}\nDuration: {metadata.get('duration', 0)}s"
                    )
                    await query.message.delete()

        except httpx.TimeoutException:
            logger.error("Request timed out, retrying...")
            await processing_msg.edit_text("Timed out, but I’m retrying… Hold tight.")
            raise  # Let retry logic handle
        except Exception as e:
            logger.error(f"Download fucked up: {str(e)}")
            await processing_msg.edit_text(f"Something went to shit: {str(e)}")

def main():
    logger.info("Starting Telegram bot")
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()