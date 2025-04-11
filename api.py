from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
import yt_dlp
from pydantic import BaseModel
import uvicorn
import logging
import os
import shutil
import uuid
from starlette.background import BackgroundTask
import re
from time import time

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.DEBUG
)
logger = logging.getLogger(__name__)

app = FastAPI(title="SIERRA's Fuckin' YouTube DL API")

DOWNLOAD_DIR = "downloads"
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

class VideoRequest(BaseModel):
    url: str
    format: str = "mp4_720"

def cleanup_files(*files):
    for f in files:
        if f and os.path.exists(f):
            try:
                os.remove(f)
                logger.debug(f"Cleaned up: {f}")
            except Exception as e:
                logger.error(f"Cleanup failed for {f}: {str(e)}")

def sanitize_filename(filename):
    return re.sub(r'[<>:"/\\|?*]', '', filename).strip()

@app.get("/")
async def root():
    return {"message": "SIERRA's YouTube DL API is fuckin' live. Hit /download with a URL."}

@app.get("/ping")
async def ping():
    return {"message": "Pong, motherfucker"}

@app.post("/download")
async def download_video(request: VideoRequest):
    start_time = time()
    logger.info(f"Got POST request: URL={request.url}, Format={request.format}")
    try:
        valid_formats = ["mp4_360", "mp4_720", "mp4_1080", "mp3_64", "mp3_128", "mp3_192", "mp3_256", "mp3_320", "mp4_audio"]
        if request.format not in valid_formats:
            logger.error(f"Invalid format: {request.format}")
            raise ValueError(f"Format’s bullshit. Use: {', '.join(valid_formats)}")

        file_id = str(uuid.uuid4())
        temp_file = os.path.join(DOWNLOAD_DIR, f"temp_{file_id}")
        temp_output = f"{temp_file}.%(ext)s"

        ydl_opts = {
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "outtmpl": temp_output,
        }

        cleanup_list = []

        if request.format.startswith("mp4_"):
            quality = request.format.split("_")[1]
            ydl_opts["format"] = f"bestvideo[height<={quality}]+bestaudio/best[height<={quality}]"
            ydl_opts["merge_output_format"] = "mp4"
        elif request.format == "mp4_audio":
            ydl_opts["format"] = "bestaudio"
            ydl_opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "m4a"}]
        else:  # mp3
            bitrate = request.format.split("_")[1]
            ydl_opts["format"] = "bestaudio"
            ydl_opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": bitrate,
            }]

        logger.debug(f"yt-dlp options: {ydl_opts}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            logger.debug(f"Downloading: {request.url}")
            info = ydl.extract_info(request.url, download=True)
            logger.debug(f"Download took: {time() - start_time:.2f}s")

        title = sanitize_filename(info.get("title", "Unknown_Video"))
        file_ext = "mp4" if request.format.startswith("mp4_") else "m4a" if request.format == "mp4_audio" else "mp3"
        downloaded_file = next((f"{temp_file}.{ext}" for ext in ["mp4", "m4a", "mp3"] if os.path.exists(f"{temp_file}.{ext}")), None)
        if not downloaded_file:
            logger.error("No file found after download")
            raise ValueError("Download fucked up, no file found.")

        output_file = os.path.join(DOWNLOAD_DIR, f"{title}_{file_id}.{file_ext}")
        shutil.move(downloaded_file, output_file)

        if not os.path.exists(output_file):
            logger.error(f"Output file missing: {output_file}")
            raise ValueError(f"Output file fucked up, doesn’t exist: {output_file}")

        metadata = {
            "title": info.get("title", "Unknown"),
            "duration": info.get("duration", 0),
            "thumbnail": info.get("thumbnail", ""),
            "uploader": info.get("uploader", "Unknown"),
        }

        logger.debug(f"Serving file: {output_file}, total time: {time() - start_time:.2f}s")
        cleanup_list.append(downloaded_file)
        return FileResponse(
            path=output_file,
            filename=f"{title}.{file_ext}",
            media_type="application/octet-stream",
            headers={"X-Metadata": str(metadata)},
            background=BackgroundTask(cleanup_files, *[f for f in cleanup_list if f], output_file)
        )

    except Exception as e:
        logger.error(f"Download fucked up: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Fucked up somewhere: {str(e)}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))  # Render sets PORT
    logger.info(f"Starting API server on port {port}")
    uvicorn.run("api:app", host="0.0.0.0", port=port, reload=True, log_level="debug")