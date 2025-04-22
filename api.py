from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
import yt_dlp
from pydantic import BaseModel
import uvicorn
import logging
import os
import shutil
import subprocess
import uuid
from starlette.background import BackgroundTask
import re
from time import time
import urllib.parse

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

def progress_hook(d):
    if d["status"] == "downloading":
        percent = d.get("downloaded_bytes", 0) / d.get("total_bytes", 1) * 100
        eta = d.get("eta", "Unknown")
        logger.info(f"Download progress: {percent:.1f}%, ETA: {eta}s")
    elif d["status"] == "finished":
        logger.info("Download complete, processing...")

@app.get("/")
async def root():
    return {"message": "SIERRA's YouTube DL API is fuckin' live. Hit /download with a URL or search."}

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
        thumbnail_file = os.path.join(DOWNLOAD_DIR, f"thumb_{file_id}.jpg")

        # Handle search or URL
        parsed_url = urllib.parse.urlparse(request.url)
        if not parsed_url.netloc:  # Assume search query
            search_query = f"ytsearch:{request.url}"
            logger.info(f"Searching YouTube for: {request.url}")
        else:
            search_query = request.url

        ydl_opts = {
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "outtmpl": temp_output,
            "progress_hooks": [progress_hook],
            "writethumbnail": True,
        }

        cleanup_list = []

        if request.format.startswith("mp4_"):
            quality = request.format.split("_")[1]
            ydl_opts["format"] = f"best[height<={quality}]/bestvideo[height<={quality}]+bestaudio"
            ydl_opts["merge_output_format"] = "mp4"
        elif request.format == "mp4_audio":
            ydl_opts["format"] = "bestaudio"
            ydl_opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "m4a"}]
        else:  # mp3
            ydl_opts["format"] = "bestaudio"
            ydl_opts["postprocessors"] = []

        logger.debug(f"yt-dlp options: {ydl_opts}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            logger.debug(f"Downloading: {search_query}")
            info = ydl.extract_info(search_query, download=True)
            logger.debug(f"Download took: {time() - start_time:.2f}s")

        title = sanitize_filename(info.get("title", "Unknown_Video"))
        file_ext = "mp4" if request.format.startswith("mp4_") else "m4a" if request.format == "mp4_audio" else "mp3"
        downloaded_file = next((f"{temp_file}.{ext}" for ext in ["mp4", "m4a", "webm", "mkv"] if os.path.exists(f"{temp_file}.{ext}")), None)
        if not downloaded_file:
            logger.error("No file found after download")
            raise ValueError("Download fucked up, no file found.")

        output_file = os.path.join(DOWNLOAD_DIR, f"{title}_{file_id}.{file_ext}")

        if request.format.startswith("mp4_"):
            if downloaded_file.endswith(".mp4"):
                shutil.move(downloaded_file, output_file)
            else:
                # Fallback: Download video and audio separately, merge with ffmpeg
                video_file = f"{temp_file}_video.%(ext)s"
                audio_file = f"{temp_file}_audio.m4a"
                # Download video
                video_opts = ydl_opts.copy()
                video_opts["format"] = f"bestvideo[height<={quality}]"
                video_opts["outtmpl"] = video_file
                with yt_dlp.YoutubeDL(video_opts) as ydl:
                    ydl.extract_info(search_query, download=True)
                video_downloaded = next((f"{temp_file}_video.{ext}" for ext in ["mp4", "webm", "mkv"] if os.path.exists(f"{temp_file}_video.{ext}")), None)
                # Download audio
                audio_opts = ydl_opts.copy()
                audio_opts["format"] = "bestaudio"
                audio_opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "m4a"}]
                audio_opts["outtmpl"] = audio_file
                with yt_dlp.YoutubeDL(audio_opts) as ydl:
                    ydl.extract_info(search_query, download=True)
                if video_downloaded and os.path.exists(audio_file):
                    logger.debug(f"Merging video: {video_downloaded}, audio: {audio_file}")
                    result = subprocess.run(
                        ["ffmpeg", "-i", video_downloaded, "-i", audio_file, "-c:v", "copy", "-c:a", "aac", "-preset", "ultrafast", "-y", output_file],
                        check=True, capture_output=True, text=True
                    )
                    logger.debug(f"ffmpeg stdout: {result.stdout}, stderr: {result.stderr}")
                    cleanup_list.extend([video_downloaded, audio_file])
                else:
                    logger.error("Video or audio download failed")
                    raise ValueError("Couldn’t merge video and audio")
            logger.debug(f"MP4 processing took: {time() - start_time:.2f}s")
        elif request.format == "mp4_audio":
            shutil.move(downloaded_file, output_file)
        else:  # mp3
            bitrate = request.format.split("_")[1] + "k"
            logger.debug(f"Converting to MP3 at {bitrate}")
            result = subprocess.run(
                ["ffmpeg", "-i", downloaded_file, "-c:a", "mp3", "-b:a", bitrate, "-preset", "ultrafast", "-y", output_file],
                check=True, capture_output=True, text=True
            )
            logger.debug(f"ffmpeg stdout: {result.stdout}, stderr: {result.stderr}")
            logger.debug(f"ffmpeg took: {time() - start_time:.2f}s")

        if not os.path.exists(output_file):
            logger.error(f"Output file missing: {output_file}")
            raise ValueError(f"Output file fucked up, doesn’t exist: {output_file}")

        # Handle thumbnail
        if os.path.exists(f"{temp_file}.jpg"):
            shutil.move(f"{temp_file}.jpg", thumbnail_file)
            cleanup_list.append(thumbnail_file)
        else:
            thumbnail_file = None
            logger.warning("No thumbnail found")

        metadata = {
            "title": info.get("title", "Unknown"),
            "duration": info.get("duration", 0),
            "thumbnail": thumbnail_file if thumbnail_file else info.get("thumbnail", ""),
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
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"Starting API on port {port}")
    uvicorn.run("api:app", host="0.0.0.0", port=port)