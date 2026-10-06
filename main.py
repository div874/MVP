import os
import shutil
import tempfile
import subprocess
import json
import base64
import logging
from typing import Optional
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from openai import OpenAI, OpenAIError

# Load environment variables
load_dotenv()

# Setup structured logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("reel_intelligence")

# --- Xkiro AI Configuration (OpenAI-compatible) ---
XKIRO_API_KEY = os.getenv("XKIRO_API_KEY")
XKIRO_BASE_URL = os.getenv("XKIRO_BASE_URL", "https://api.xkiro.com/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "qwen/qwen3.8-omni-flash:free")

if not XKIRO_API_KEY:
    raise RuntimeError("XKIRO_API_KEY is not set. Please add it to your .env file.")

# Initialize OpenAI-compatible Xkiro client
xkiro_client = OpenAI(
    api_key=XKIRO_API_KEY,
    base_url=XKIRO_BASE_URL,
)

# Initialize FastAPI Application
app = FastAPI(
    title="Reel Content Intelligence API",
    description="API for uploading reels and analyzing content patterns using Xkiro AI multimodal vision.",
    version="1.0.0"
)

# Configure CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Upload directory (OS temp directory to prevent Live Server workspace auto-reload)
UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "mvp_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB limit


def check_ffmpeg():
    """Verify FFmpeg is available on system PATH."""
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except Exception:
        logger.error("[VIDEO] FFmpeg is missing from system PATH.")
        raise HTTPException(status_code=500, detail="FFmpeg is not installed or not found on server PATH.")


def extract_frames_and_metadata(video_path: str):
    """
    Extracts representative video frames (1 frame every 2 seconds, max 15 frames)
    and inspects audio stream presence using FFmpeg/ffprobe.
    """
    check_ffmpeg()
    
    # 1. Probe video duration & audio streams
    probe_cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration:stream=codec_type",
        "-of", "json", video_path
    ]
    try:
        probe_res = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
        probe_data = json.loads(probe_res.stdout)
    except Exception as e:
        logger.error(f"[VIDEO] ffprobe failed on file: {e}")
        raise HTTPException(status_code=400, detail="Invalid video file or corrupt MP4 metadata.")

    duration_sec = float(probe_data.get("format", {}).get("duration", 0))
    streams = probe_data.get("streams", [])
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    
    logger.info(f"[VIDEO] Duration: {round(duration_sec, 2)}s | Has Audio Stream: {has_audio}")
    print(f"[AUDIO] Audio stream detected: {has_audio} (duration: {round(duration_sec, 2)}s)")

    # 2. Extract frames (1 frame every 2 seconds, scaled to 800px width, capped at max 10 frames)
    frames_tmp_dir = tempfile.mkdtemp(prefix="mvp_frames_")
    try:
        frame_pattern = os.path.join(frames_tmp_dir, "frame_%03d.jpg")
        ffmpeg_cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-vf", "fps=1/2,scale=800:-1",
            "-q:v", "2",
            frame_pattern
        ]
        subprocess.run(ffmpeg_cmd, capture_output=True, check=True)
        
        extracted_files = sorted([
            os.path.join(frames_tmp_dir, f) for f in os.listdir(frames_tmp_dir) if f.endswith(".jpg")
        ])

        if not extracted_files:
            logger.error("[FRAMES] FFmpeg produced 0 frame images.")
            raise HTTPException(status_code=400, detail="Could not extract any valid video frames from video.")

        # Cap at 10 representative lightweight frames (800px width)
        if len(extracted_files) > 10:
            step = len(extracted_files) // 10
            extracted_files = extracted_files[::step][:10]

        print(f"[FRAMES] Extracted {len(extracted_files)} representative lightweight frames (800px) for multimodal vision analysis.")

        # Convert frame images to base64 Data URIs
        frames_b64 = []
        for img_path in extracted_files:
            with open(img_path, "rb") as f:
                b64_str = base64.b64encode(f.read()).decode("utf-8")
                frames_b64.append(f"data:image/jpeg;base64,{b64_str}")

        return {
            "duration_sec": round(duration_sec, 2),
            "has_audio": has_audio,
            "frame_count": len(frames_b64),
            "frames_b64": frames_b64
        }
    finally:
        # Delete temporary extracted frame image files
        shutil.rmtree(frames_tmp_dir, ignore_errors=True)
        logger.info("[FRAMES] Cleaned up temporary frame image files.")


def filter_safe_frames(frames_b64: list, model_id: str) -> list:
    """
    Diagnostic helper that tests individual frames against xKiro to filter out
    any frame that triggers provider safety policy rejection.
    """
    safe_frames = []
    for idx, frame_uri in enumerate(frames_b64):
        try:
            xkiro_client.chat.completions.create(
                model=model_id,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Describe this frame in 5 words."},
                            {"type": "image_url", "image_url": {"url": frame_uri}}
                        ]
                    }
                ],
                max_tokens=20
            )
            safe_frames.append(frame_uri)
        except Exception as e:
            err_str = str(e).lower()
            if "safety" in err_str or "rejected" in err_str or "400" in err_str:
                print(f"[SAFETY] Frame #{idx+1} triggered provider safety policy — filtering out this frame.")
                logger.warning(f"[SAFETY] Frame #{idx+1} filtered out due to safety policy.")
            else:
                safe_frames.append(frame_uri)
    return safe_frames


def analyze_multimodal_reel(frames_data: dict, caption: Optional[str] = None, source_info: str = "Uploaded MP4 Reel") -> dict:
    """
    Sends extracted representative frames + caption to Xkiro AI (qwen/qwen3.8-omni-flash:free)
    using OpenAI-compatible vision input items (image_url).

    WHY FALLBACK PIPELINE IS USED:
    -----------------------------
    Direct video file upload (data:video/mp4;base64 or video_url) is NOT supported
    by xKiro's OpenAI-compatible Chat Completions endpoint (returns HTTP 500 server error).
    Therefore, we extract 1 representative frame every 2 seconds via FFmpeg, convert
    them to JPEG base64 Data URIs, and send them as visual vision input items (type: image_url).
    """
    frames_b64 = frames_data.get("frames_b64", [])
    has_audio = frames_data.get("has_audio", False)
    duration = frames_data.get("duration_sec", 0)

    system_prompt = (
        "You are an expert social media content intelligence analyst for creators and B2B brands.\n"
        "Analyze the provided sequence of representative video frames extracted from a Reel (1 frame every 2 seconds).\n\n"
        "CRITICAL REQUIREMENTS:\n"
        "1. Return ONLY a single valid JSON object adhering strictly to the schema provided.\n"
        "2. Do NOT invent or assume details that cannot be clearly observed from the frames, audio notes, or caption. Use null or [] for unobservable fields.\n"
        "3. Do NOT wrap output in explanations or commentary outside the JSON."
    )

    json_schema_prompt = """Return ONLY a JSON object matching this exact structure:
{
  "summary": "Brief overall summary of the reel content",
  "topic": "Main topic discussed or visually demonstrated",
  "content_category": "Category e.g. Educational, B2B Showcase, Travel, Entertainment, Lifestyle",
  "hook": "Visual or textual hook observed in the opening frames",
  "hook_type": "Visual / Text Overlay / Action / Question / Story",
  "target_audience": "Target demographic, interest group, or B2B buyer role",
  "storytelling_format": "Format e.g. Process B-roll Montage, Voiceover Showcase, Talking Head, Listicle",
  "visual_style": "Visual aesthetic e.g. Cinematic, High-Contrast, Raw Vlog, Fast Cuts",
  "emotional_trigger": "Core emotion targeted e.g. Curiosity, Trust, Awe, FOMO, Humor, Inspiration",
  "key_messages": ["Key message 1", "Key message 2"],
  "on_screen_text": ["Text overlay 1", "Text overlay 2"],
  "call_to_action": "CTA if visible in frames/caption, else null",
  "engagement_potential": {
    "level": "High | Medium | Low",
    "reason": "Detailed reasoning based on hook, pacing, and visual appeal"
  },
  "content_strengths": ["Strength 1", "Strength 2"],
  "content_weaknesses": ["Weakness 1"],
  "content_opportunities": ["Actionable opportunity for creators or businesses"],
  "recommended_content_angle": "How a creator or business can adapt or recreate this content angle"
}"""

    prompt_text = (
        f"Reel Metadata:\n"
        f"- Source: {source_info}\n"
        f"- Video Duration: {duration} seconds\n"
        f"- Audio Stream Present: {'Yes' if has_audio else 'No (Silent Video)'}\n"
        f"- User Caption: {caption if caption else 'No caption provided.'}\n\n"
        f"{json_schema_prompt}"
    )

    # Build OpenAI multimodal message content
    content_list = [{"type": "text", "text": prompt_text}]
    for frame_uri in frames_b64:
        content_list.append({
            "type": "image_url",
            "image_url": {"url": frame_uri}
        })

    # Models fallback sequence (free vision-capable models only to avoid 403 paid errors)
    models_to_try = [MODEL_NAME, "qwen/qwen3-vl-plus:free", "qwen/qwen3.5-omni-flash:free"]
    last_error = None

    for current_model in models_to_try:
        print(f"[XKIRO] Sending {len(frames_b64)} video frames to model '{current_model}'...")
        logger.info(f"[XKIRO] Initiating multimodal chat completion request with {len(frames_b64)} frames using '{current_model}'.")

        try:
            response = xkiro_client.chat.completions.create(
                model=current_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content_list}
                ],
                temperature=0.2
            )

            raw_ai_text = response.choices[0].message.content.strip()
            print(f"[ANALYSIS] Received AI response from '{current_model}' ({response.usage.total_tokens} total tokens). Parsing JSON...")

            # Clean markdown code blocks if present
            clean_json_str = raw_ai_text
            if clean_json_str.startswith("```"):
                clean_json_str = clean_json_str.split("```")[1]
                if clean_json_str.startswith("json"):
                    clean_json_str = clean_json_str[4:]
            clean_json_str = clean_json_str.strip()

            try:
                parsed_analysis = json.loads(clean_json_str)
                print("[ANALYSIS] Structured JSON parsed successfully.")
            except json.JSONDecodeError as parse_err:
                logger.warning(f"[ANALYSIS] Raw AI response was not strict JSON: {parse_err}")
                parsed_analysis = {
                    "summary": raw_ai_text,
                    "parse_error": "AI output could not be parsed as strict JSON.",
                    "raw_text": raw_ai_text
                }

            return {
                "success": True,
                "model": response.model,
                "analysis": parsed_analysis,
                "raw_text": raw_ai_text,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }
            }

        except OpenAIError as e:
            err_msg = str(e)
            logger.warning(f"[XKIRO] API error with '{current_model}': {err_msg}")
            last_error = f"xKiro API error ({current_model}): {err_msg}"

            # If safety error occurs on frame batch, filter out flagged frame(s) and retry
            if ("safety" in err_msg.lower() or "rejected" in err_msg.lower()) and len(frames_b64) > 1:
                print(f"[SAFETY] Safety policy error detected on frame batch. Filtering safe frames individually...")
                safe_frames = filter_safe_frames(frames_b64, current_model)
                if safe_frames and len(safe_frames) < len(frames_b64):
                    print(f"[SAFETY] Successfully filtered out {len(frames_b64) - len(safe_frames)} flagged frame(s). Retrying with {len(safe_frames)} safe frames...")
                    retry_content_list = [{"type": "text", "text": prompt_text}]
                    for frame_uri in safe_frames:
                        retry_content_list.append({"type": "image_url", "image_url": {"url": frame_uri}})
                    try:
                        retry_resp = xkiro_client.chat.completions.create(
                            model=current_model,
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": retry_content_list}
                            ],
                            temperature=0.2
                        )
                        raw_ai_text = retry_resp.choices[0].message.content.strip()
                        clean_json_str = raw_ai_text
                        if clean_json_str.startswith("```"):
                            clean_json_str = clean_json_str.split("```")[1]
                            if clean_json_str.startswith("json"):
                                clean_json_str = clean_json_str[4:]
                        clean_json_str = clean_json_str.strip()
                        try:
                            parsed_analysis = json.loads(clean_json_str)
                        except json.JSONDecodeError:
                            parsed_analysis = {"summary": raw_ai_text, "raw_text": raw_ai_text}
                        return {
                            "success": True,
                            "model": retry_resp.model,
                            "analysis": parsed_analysis,
                            "raw_text": raw_ai_text,
                            "usage": {
                                "prompt_tokens": retry_resp.usage.prompt_tokens,
                                "completion_tokens": retry_resp.usage.completion_tokens,
                                "total_tokens": retry_resp.usage.total_tokens,
                            }
                        }
                    except Exception as retry_err:
                        logger.error(f"[SAFETY] Retry with safe frames failed on '{current_model}': {retry_err}")

            # If safety error persists, continue to next fallback vision model
            if "safety" in err_msg.lower() or "rejected" in err_msg.lower() or "400" in err_msg:
                print(f"[XKIRO] Model '{current_model}' safety/API error. Trying fallback vision model...")
                continue
            else:
                break
        except Exception as e:
            err_msg = str(e)
            logger.error(f"[XKIRO] Unexpected error with '{current_model}': {err_msg}")
            last_error = f"Unexpected error ({current_model}): {err_msg}"
            break

    return {"success": False, "error": last_error or "All vision models failed to process the request."}




# --- API ENDPOINTS ---

@app.get("/")
def read_root():
    return {
        "status": "online",
        "message": "Reel Content Intelligence API (Multimodal Enabled)",
        "xkiro_base_url": XKIRO_BASE_URL,
        "xkiro_model": MODEL_NAME
    }


@app.get("/api/models")
def list_models():
    try:
        models = xkiro_client.models.list()
        return {"status": "success", "models": [m.id for m in models.data]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def download_reel_from_url(url: str) -> dict:
    """
    Downloads an Instagram Reel, TikTok, or YouTube Shorts video URL
    into OS temp directory using yt_dlp. Returns path to downloaded MP4 file and extracted caption.
    """
    tmp_dir = tempfile.mkdtemp(prefix="mvp_url_download_")
    out_template = os.path.join(tmp_dir, "reel.%(ext)s")
    
    ydl_opts = {
        "outtmpl": out_template,
        "format": "mp4/bestvideo+bestaudio/best",
        "quiet": True,
        "no_warnings": True,
    }
    
    logger.info(f"[URL] Downloading Reel from link: {url}")
    print(f"[URL] Downloading Reel from URL: {url}")
    
    try:
        import yt_dlp
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            video_path = ydl.prepare_filename(info)
            caption_text = info.get("description") or info.get("title") or ""
            
        return {
            "temp_dir": tmp_dir,
            "video_path": video_path,
            "title_caption": caption_text,
            "duration": info.get("duration")
        }
    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        logger.error(f"[URL] Failed to download Reel from URL: {e}")
        raise HTTPException(status_code=400, detail=f"Could not download video from provided URL: {str(e)}")


def process_single_url_sync(url: str, caption: Optional[str] = None) -> dict:
    """Helper to synchronously process a single Reel URL (download, extract frames, analyze)."""
    reel_data = download_reel_from_url(url)
    temp_video_path = reel_data["video_path"]
    url_caption = reel_data["title_caption"]
    
    try:
        frames_data = extract_frames_and_metadata(temp_video_path)
        effective_caption = f"{caption}\n{url_caption}".strip() if caption else url_caption
        source_info = f"Reel URL: {url}"
        
        ai_result = analyze_multimodal_reel(
            frames_data=frames_data,
            caption=effective_caption,
            source_info=source_info
        )
        
        return {
            "reel_url": url,
            "duration_sec": frames_data.get("duration_sec"),
            "has_audio": frames_data.get("has_audio"),
            "frames_analyzed": frames_data.get("frame_count"),
            "effective_caption": effective_caption,
            "ai_analysis": ai_result
        }
    finally:
        shutil.rmtree(reel_data["temp_dir"], ignore_errors=True)


def synthesize_batch_reel_intelligence(reels_results: list) -> dict:
    """Synthesizes cross-Reel content patterns, hooks, and opportunities across multiple analyzed Reels."""
    valid_analyses = [r["ai_analysis"]["analysis"] for r in reels_results if r.get("ai_analysis", {}).get("success") and isinstance(r["ai_analysis"].get("analysis"), dict)]
    
    if not valid_analyses:
        return {"summary": "Batch processing completed. Cross-Reel synthesis unavailable."}

    summary_prompt = f"""You are a senior social media content strategist.
Analyze the following JSON analyses extracted from {len(valid_analyses)} different Reels:

{json.dumps(valid_analyses, indent=2)}

Provide a Cross-Reel Content Intelligence Synthesis. Return ONLY a JSON object matching this exact structure:
{{
  "batch_summary": "High-level synthesis of patterns across all analyzed Reels",
  "dominant_hook_patterns": ["Hook pattern 1", "Hook pattern 2"],
  "common_visual_styles": ["Style 1", "Style 2"],
  "target_audience_overlap": "Combined audience insights across the Reels",
  "top_content_strengths": ["Shared strength 1", "Shared strength 2"],
  "cross_reel_opportunities": ["Opportunity 1 for creators/brands", "Opportunity 2"],
  "recommended_creator_strategy": "Actionable content strategy derived from analyzing these Reels together"
}}"""

    try:
        resp = xkiro_client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": summary_prompt}],
            temperature=0.2
        )
        clean_text = resp.choices[0].message.content.strip()
        if clean_text.startswith("```"):
            clean_text = clean_text.split("```")[1]
            if clean_text.startswith("json"):
                clean_text = clean_text[4:]
        return json.loads(clean_text.strip())
    except Exception as e:
        logger.warning(f"[BATCH] Cross-Reel synthesis error: {e}")
        return {
            "batch_summary": f"Analyzed {len(valid_analyses)} Reels in parallel.",
            "dominant_hook_patterns": [a.get("hook") for a in valid_analyses if a.get("hook")],
            "top_content_strengths": [s for a in valid_analyses for s in a.get("content_strengths", [])][:3]
        }


import asyncio

@app.post("/api/upload-reel")
async def upload_reel(
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
    urls: Optional[str] = Form(None),
    caption: Optional[str] = Form(None)
):
    raw_urls_str = urls or url or ""
    url_list = [u.strip() for u in raw_urls_str.splitlines() if u.strip().startswith("http")]

    if not file and not url_list:
        raise HTTPException(status_code=400, detail="Either a video file or Reel link(s) must be provided.")

    # 1. Handle Multiple Reel URLs in Parallel
    if len(url_list) > 1:
        print(f"[BATCH] Processing {len(url_list)} Reel URLs concurrently in parallel...")
        logger.info(f"[BATCH] Initiating parallel processing for {len(url_list)} URLs.")

        # Run parallel workers using asyncio.gather + threadpool
        results = await asyncio.gather(*[
            asyncio.to_thread(process_single_url_sync, u, caption)
            for u in url_list
        ])

        print(f"[BATCH] Parallel processing of {len(url_list)} Reels complete. Synthesizing Cross-Reel Intelligence...")
        synthesis = await asyncio.to_thread(synthesize_batch_reel_intelligence, results)

        return {
            "status": "success",
            "message": f"Successfully analyzed {len(url_list)} Reels concurrently in parallel!",
            "batch_count": len(url_list),
            "reels": results,
            "ai_analysis": {
                "success": True,
                "model": MODEL_NAME,
                "analysis": synthesis,
                "is_batch_synthesis": True
            }
        }

    # 2. Handle Single File Upload
    elif file:
        print(f"[UPLOAD] Received file upload: {file.filename}")

        valid_exts = (".mp4", ".mov", ".webm", ".mkv", ".avi", ".quicktime")
        if not file.filename.lower().endswith(valid_exts):
            logger.error(f"[UPLOAD] Unsupported format: {file.filename}")
            raise HTTPException(status_code=400, detail="Unsupported file format. Please upload MP4, MOV, or WEBM video.")

        temp_file_path = os.path.join(UPLOAD_DIR, file.filename)
        
        try:
            with open(temp_file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)

            file_size = os.path.getsize(temp_file_path)
            print(f"[UPLOAD] File saved to OS temp path: {temp_file_path} ({round(file_size / (1024 * 1024), 2)} MB)")

            if file_size > MAX_FILE_SIZE_BYTES:
                raise HTTPException(status_code=400, detail="File too large. Maximum allowed size is 100 MB.")

            frames_data = extract_frames_and_metadata(temp_file_path)
            source_info = f"Uploaded File: {file.filename} ({round(file_size / (1024 * 1024), 2)} MB)"
            ai_result = analyze_multimodal_reel(
                frames_data=frames_data,
                caption=caption,
                source_info=source_info
            )

            file_info = {
                "source_type": "file_upload",
                "filename": file.filename,
                "content_type": file.content_type,
                "size_mb": round(file_size / (1024 * 1024), 2),
                "duration_sec": frames_data.get("duration_sec"),
                "has_audio": frames_data.get("has_audio"),
                "frames_analyzed": frames_data.get("frame_count")
            }

            return {
                "status": "success",
                "message": "Reel multimodal analysis complete!",
                "caption": caption if caption else None,
                "data": file_info,
                "ai_analysis": ai_result
            }

        finally:
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
                print(f"[UPLOAD] Deleted temporary video file: {temp_file_path}")

    # 3. Handle Single Reel URL
    elif len(url_list) == 1:
        target_url = url_list[0]
        print(f"[URL] Received single Reel URL link: {target_url}")
        res = process_single_url_sync(target_url, caption)
        
        file_info = {
            "source_type": "url_link",
            "reel_url": target_url,
            "duration_sec": res.get("duration_sec"),
            "has_audio": res.get("has_audio"),
            "frames_analyzed": res.get("frames_analyzed")
        }
        
        return {
            "status": "success",
            "message": "Reel URL fetched and analyzed successfully!",
            "caption": res.get("effective_caption"),
            "data": file_info,
            "ai_analysis": res.get("ai_analysis")
        }




@app.post("/api/analyze")
async def analyze_content(
    caption: str = Form(...),
    source_info: Optional[str] = Form(default="Direct text input")
):
    if not caption.strip():
        raise HTTPException(status_code=400, detail="Caption cannot be empty.")

    dummy_frames = {"frames_b64": [], "has_audio": False, "duration_sec": 0}
    ai_result = analyze_multimodal_reel(frames_data=dummy_frames, caption=caption, source_info=source_info)

    return {
        "status": "success",
        "message": "Content analyzed successfully!",
        "ai_analysis": ai_result
    }


# --- Diagnostic Endpoint: Single Frame Vision Test ---
@app.post("/api/test-frame")
async def test_single_frame(
    file: UploadFile = File(...)
):
    """
    Diagnostic Endpoint:
    1. Saves uploaded MP4.
    2. Extracts 1 frame from middle of video.
    3. Logs image dimensions, format, file size, JPEG magic header, data URL prefix.
    4. Sends ONLY that single JPEG frame to Qwen.
    5. If Qwen fails with safety policy error, runs diagnostic matrix against alt vision models.
    """
    check_ffmpeg()

    print(f"[TEST-FRAME] Received test upload: {file.filename}")
    temp_file_path = os.path.join(UPLOAD_DIR, f"test_{file.filename}")

    try:
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        file_size = os.path.getsize(temp_file_path)
        print(f"[TEST-FRAME] Saved MP4 ({round(file_size/(1024*1024),2)} MB) to {temp_file_path}")

        # 1. Probe duration
        probe_cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "json", temp_file_path
        ]
        probe_res = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
        duration = float(json.loads(probe_res.stdout).get("format", {}).get("duration", 0))
        middle_sec = round(duration / 2, 2)

        # 2. Extract single frame
        tmp_dir = tempfile.mkdtemp(prefix="single_frame_api_")
        frame_filename = os.path.join(tmp_dir, "frame_middle.jpg")

        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-ss", str(middle_sec),
            "-i", temp_file_path,
            "-vframes", "1",
            "-vf", "scale=800:-1",
            frame_filename
        ]
        subprocess.run(ffmpeg_cmd, capture_output=True, check=True)

        # 3. Inspect image properties
        from PIL import Image
        with Image.open(frame_filename) as img:
            width, height = img.size
            img_format = img.format

        img_bytes_count = os.path.getsize(frame_filename)
        with open(frame_filename, "rb") as f:
            raw_bytes = f.read()

        has_jpeg_header = raw_bytes.startswith(b"\xff\xd8\xff")
        b64_str = base64.b64encode(raw_bytes).decode("utf-8")
        data_url = f"data:image/jpeg;base64,{b64_str}"
        prefix_50 = data_url[:50]

        diagnostics = {
            "filename": os.path.basename(frame_filename),
            "dimensions": f"{width}x{height}",
            "format": img_format,
            "file_size_bytes": img_bytes_count,
            "valid_jpeg_header": has_jpeg_header,
            "base64_converted": True,
            "data_url_prefix_50_chars": f"{prefix_50}...",
            "content_type_sent": "image_url",
            "model_used": MODEL_NAME
        }

        print("=== FRAME DIAGNOSTICS LOG ===")
        for k, v in diagnostics.items():
            print(f"- {k}: {v}")

        # 4. Send single JPEG frame to Qwen
        def call_model(model_id):
            print(f"[XKIRO] Sending single JPEG frame ({width}x{height}, {round(img_bytes_count/1024,1)} KB) to model '{model_id}'...")
            try:
                resp = xkiro_client.chat.completions.create(
                    model=model_id,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "Describe what is clearly visible in this frame image in 2 sentences."},
                                {"type": "image_url", "image_url": {"url": data_url}}
                            ]
                        }
                    ],
                    temperature=0.2
                )
                return True, resp.choices[0].message.content.strip()
            except Exception as e:
                return False, str(e)

        primary_success, primary_result = call_model(MODEL_NAME)

        matrix = {}
        diagnostic_conclusion = ""

        if primary_success:
            diagnostic_conclusion = f"Single frame test PASSED cleanly with primary model '{MODEL_NAME}'."
            print(f"[TEST-FRAME] SUCCESS: {primary_result}")
        else:
            print(f"[TEST-FRAME] PRIMARY MODEL ERROR: {primary_result}")
            if "safety" in primary_result.lower() or "provider's safety policy" in primary_result.lower():
                print("[TEST-FRAME] Safety policy error detected! Running model comparison matrix...")
                alt_models = ["qwen/qwen3-vl-plus:free", "google/gemini-2.5-flash", "z-ai/glm-4.6v"]
                for alt in alt_models:
                    ok, res_text = call_model(alt)
                    matrix[alt] = {"success": ok, "response_or_error": res_text}

                if any(v["success"] for v in matrix.values()):
                    diagnostic_conclusion = (
                        f"Image encoding and format are 100% VALID. Rejection is SPECIFIC to '{MODEL_NAME}' safety filter "
                        f"because alternative vision model succeeded."
                    )
                else:
                    diagnostic_conclusion = (
                        "Rejection occurs across multiple vision models. "
                        "Rejection is specific to xKiro's media safety layer or input image content."
                    )

        # Clean up
        os.remove(frame_filename)
        os.rmdir(tmp_dir)

        return {
            "status": "success" if primary_success else "safety_or_api_error",
            "diagnostics": diagnostics,
            "primary_model": MODEL_NAME,
            "primary_success": primary_success,
            "primary_response": primary_result if primary_success else None,
            "primary_error": primary_result if not primary_success else None,
            "alternative_models_matrix": matrix if matrix else None,
            "conclusion": diagnostic_conclusion
        }

    finally:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

