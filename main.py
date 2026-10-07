import os
import shutil
import tempfile
import subprocess
import json
import base64
import logging
import math
import re
from collections import Counter
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


# --- PROGRAMMATIC REEL SIMILARITY ENGINE & CONFIGURATION ---
# Note: Initial thresholds and weights are isolated heuristic MVP settings that can be calibrated
# using labeled training datasets in future iterations.
RELATIONSHIP_CONFIG = {
    "WEIGHT_SEMANTIC": 0.30,
    "WEIGHT_DOMAIN": 0.25,
    "WEIGHT_TOPIC": 0.20,
    "WEIGHT_AUDIENCE": 0.15,
    "WEIGHT_INTENT": 0.05,
    "WEIGHT_KEYWORD": 0.05,
    "RELATED_THRESHOLD": 0.45,      # Combined score >= 0.45 -> RELATED
    "UNRELATED_THRESHOLD": 0.30,    # Combined score < 0.30 -> UNRELATED
}

# Domain Taxonomy for Hierarchical Category Comparison
DOMAIN_TAXONOMY = {
    "technology": ["ai", "software", "cybersecurity", "coding", "data", "hardware", "b2b tech", "dev", "tech", "scraping", "automation"],
    "marketing": ["social media", "lead generation", "sales", "b2b marketing", "advertising", "seo", "outreach", "agency"],
    "business": ["entrepreneurship", "finance", "investing", "startup", "ecommerce", "business", "b2b"],
    "entertainment": ["news", "viral incident", "humor", "storytelling", "lifestyle", "pop culture", "railway", "train", "towel", "stolen", "funny"],
    "travel": ["tourism", "vacation", "culture", "destination", "trip"],
    "food": ["cooking", "recipe", "restaurant", "culinary", "foodie"],
    "fitness": ["workout", "health", "nutrition", "sports", "gym"]
}


def tokenize_text(text: str) -> list:
    """Extract lowercase word tokens."""
    if not text:
        return []
    return re.findall(r'\b[a-z0-9]+\b', str(text).lower())


def calculate_jaccard_similarity(set1: set, set2: set) -> float:
    """Calculates Jaccard Index |A ∩ B| / |A ∪ B|."""
    if not set1 and not set2:
        return 1.0
    if not set1 or not set2:
        return 0.0
    intersection = len(set1.intersection(set2))
    union = len(set1.union(set2))
    return round(intersection / union, 4) if union > 0 else 0.0


def calculate_cosine_similarity(text1: str, text2: str) -> float:
    """Calculates TF-IDF Cosine Similarity between two text strings."""
    tokens1 = tokenize_text(text1)
    tokens2 = tokenize_text(text2)
    if not tokens1 or not tokens2:
        return 0.0

    vocab = list(set(tokens1 + tokens2))
    tf1 = Counter(tokens1)
    tf2 = Counter(tokens2)

    idf = {}
    for term in vocab:
        doc_count = (1 if term in tf1 else 0) + (1 if term in tf2 else 0)
        idf[term] = math.log((2 + 1) / (doc_count + 1)) + 1.0

    vec1 = [tf1[term] * idf[term] for term in vocab]
    vec2 = [tf2[term] * idf[term] for term in vocab]

    dot_product = sum(v1 * v2 for v1, v2 in zip(vec1, vec2))
    mag1 = math.sqrt(sum(v1 ** 2 for v1 in vec1))
    mag2 = math.sqrt(sum(v2 ** 2 for v2 in vec2))

    if mag1 == 0 or mag2 == 0:
        return 0.0
    return round(dot_product / (mag1 * mag2), 4)


def calculate_domain_similarity(domain1: str, domain2: str, category1: str = "", category2: str = "") -> float:
    """Calculates hierarchical domain similarity score (0.0 to 1.0)."""
    d1 = (domain1 or "").lower().strip()
    d2 = (domain2 or "").lower().strip()
    c1 = (category1 or "").lower().strip()
    c2 = (category2 or "").lower().strip()

    if d1 and d2 and d1 == d2:
        return 1.0

    parent1 = None
    parent2 = None
    for parent, keywords in DOMAIN_TAXONOMY.items():
        if any(k in d1 or k in c1 for k in [parent] + keywords):
            parent1 = parent
        if any(k in d2 or k in c2 for k in [parent] + keywords):
            parent2 = parent

    if parent1 and parent2 and parent1 == parent2:
        return 0.75  # Same high-level domain hierarchy
    elif (parent1 == "technology" and parent2 == "marketing") or (parent1 == "marketing" and parent2 == "technology"):
        return 0.40  # Tech & Marketing crossover
    elif (parent1 == "business" and parent2 in ("technology", "marketing")) or (parent2 == "business" and parent1 in ("technology", "marketing")):
        return 0.35  # Business & Tech/Marketing crossover
    
    return 0.0  # Substantially different domains


def evaluate_programmatic_similarity(analysis1: dict, analysis2: dict) -> dict:
    """
    Computes programmatic similarity metrics across multiple dimensions between two Reels.
    Returns internal signals and programmatic relationship determination.
    """
    # 1. Semantic Similarity (Composite text representation)
    t1 = f"{analysis1.get('summary', '')} {analysis1.get('topic', '')} {analysis1.get('content_category', '')} {analysis1.get('target_audience', '')} {' '.join(analysis1.get('key_messages', []) if isinstance(analysis1.get('key_messages'), list) else [])}"
    t2 = f"{analysis2.get('summary', '')} {analysis2.get('topic', '')} {analysis2.get('content_category', '')} {analysis2.get('target_audience', '')} {' '.join(analysis2.get('key_messages', []) if isinstance(analysis2.get('key_messages'), list) else [])}"
    semantic_sim = calculate_cosine_similarity(t1, t2)

    # 2. Domain Similarity
    domain_sim = calculate_domain_similarity(
        analysis1.get("content_category", ""),
        analysis2.get("content_category", ""),
        analysis1.get("topic", ""),
        analysis2.get("topic", "")
    )

    # 3. Topic Similarity
    top1_tokens = set(tokenize_text(f"{analysis1.get('topic', '')} {analysis1.get('content_category', '')}"))
    top2_tokens = set(tokenize_text(f"{analysis2.get('topic', '')} {analysis2.get('content_category', '')}"))
    topic_sim = calculate_jaccard_similarity(top1_tokens, top2_tokens)

    # 4. Audience Similarity
    aud1_tokens = set(tokenize_text(str(analysis1.get("target_audience", ""))))
    aud2_tokens = set(tokenize_text(str(analysis2.get("target_audience", ""))))
    audience_sim = calculate_jaccard_similarity(aud1_tokens, aud2_tokens)

    # 5. Format & Visual Style Similarity
    fmt1_tokens = set(tokenize_text(f"{analysis1.get('storytelling_format', '')} {analysis1.get('visual_style', '')}"))
    fmt2_tokens = set(tokenize_text(f"{analysis2.get('storytelling_format', '')} {analysis2.get('visual_style', '')}"))
    format_sim = calculate_jaccard_similarity(fmt1_tokens, fmt2_tokens)

    # 6. Intent / Psychological Trigger Similarity
    trig1_tokens = set(tokenize_text(str(analysis1.get("emotional_trigger", ""))))
    trig2_tokens = set(tokenize_text(str(analysis2.get("emotional_trigger", ""))))
    intent_sim = calculate_jaccard_similarity(trig1_tokens, trig2_tokens)

    # 7. Keyword & Entity Similarity
    kw1 = set(tokenize_text(" ".join((analysis1.get("key_messages") if isinstance(analysis1.get("key_messages"), list) else []) + (analysis1.get("on_screen_text") if isinstance(analysis1.get("on_screen_text"), list) else []))))
    kw2 = set(tokenize_text(" ".join((analysis2.get("key_messages") if isinstance(analysis2.get("key_messages"), list) else []) + (analysis2.get("on_screen_text") if isinstance(analysis2.get("on_screen_text"), list) else []))))
    keyword_sim = calculate_jaccard_similarity(kw1, kw2)

    # Combined Weighted Score
    combined_score = round(
        semantic_sim * RELATIONSHIP_CONFIG["WEIGHT_SEMANTIC"] +
        domain_sim * RELATIONSHIP_CONFIG["WEIGHT_DOMAIN"] +
        topic_sim * RELATIONSHIP_CONFIG["WEIGHT_TOPIC"] +
        audience_sim * RELATIONSHIP_CONFIG["WEIGHT_AUDIENCE"] +
        intent_sim * RELATIONSHIP_CONFIG["WEIGHT_INTENT"] +
        keyword_sim * RELATIONSHIP_CONFIG["WEIGHT_KEYWORD"],
        4
    )

    # Reason Codes
    reason_codes = []
    if domain_sim == 0.0:
        reason_codes.append("different_domains")
    else:
        reason_codes.append("similar_domains")

    if topic_sim < 0.15:
        reason_codes.append("different_topics")
    else:
        reason_codes.append("similar_topics")

    if audience_sim < 0.15:
        reason_codes.append("different_target_audiences")
    else:
        reason_codes.append("overlapping_target_audiences")

    if semantic_sim < 0.20:
        reason_codes.append("low_semantic_similarity")
    elif semantic_sim > 0.55:
        reason_codes.append("high_semantic_similarity")

    # Decision Layer
    if combined_score >= RELATIONSHIP_CONFIG["RELATED_THRESHOLD"]:
        status = "related"
        confidence = round(min(0.98, combined_score + 0.20), 2)
    elif combined_score < RELATIONSHIP_CONFIG["UNRELATED_THRESHOLD"]:
        status = "unrelated"
        confidence = round(min(0.98, (1.0 - combined_score)), 2)
    else:
        status = "insufficient_evidence"
        confidence = 0.50

    return {
        "status": status,
        "confidence_score": confidence,
        "signals": {
            "semantic_similarity": semantic_sim,
            "domain_similarity": domain_sim,
            "topic_similarity": topic_sim,
            "audience_similarity": audience_sim,
            "format_similarity": format_sim,
            "intent_similarity": intent_sim,
            "keyword_similarity": keyword_sim,
            "combined_score": combined_score
        },
        "reason_codes": reason_codes
    }


def evaluate_batch_pairwise_similarity(reels_list: list) -> dict:
    """Computes pairwise programmatic similarity across a collection of valid Reels."""
    if len(reels_list) < 2:
        return {"status": "single_reel", "confidence_score": 1.0, "signals": {}, "reason_codes": []}

    if len(reels_list) == 2:
        return evaluate_programmatic_similarity(reels_list[0]["analysis"], reels_list[1]["analysis"])

    # For 3+ Reels: compute pairwise matrix and average signals
    pairwise_results = []
    for i in range(len(reels_list)):
        for j in range(i + 1, len(reels_list)):
            res = evaluate_programmatic_similarity(reels_list[i]["analysis"], reels_list[j]["analysis"])
            pairwise_results.append(res)

    avg_combined = sum(p["signals"]["combined_score"] for p in pairwise_results) / len(pairwise_results)
    avg_semantic = sum(p["signals"]["semantic_similarity"] for p in pairwise_results) / len(pairwise_results)
    avg_domain = sum(p["signals"]["domain_similarity"] for p in pairwise_results) / len(pairwise_results)
    avg_topic = sum(p["signals"]["topic_similarity"] for p in pairwise_results) / len(pairwise_results)
    avg_audience = sum(p["signals"]["audience_similarity"] for p in pairwise_results) / len(pairwise_results)

    if avg_combined >= RELATIONSHIP_CONFIG["RELATED_THRESHOLD"]:
        status = "related"
        conf = round(min(0.98, avg_combined + 0.20), 2)
    elif avg_combined < RELATIONSHIP_CONFIG["UNRELATED_THRESHOLD"]:
        status = "unrelated"
        conf = round(min(0.98, (1.0 - avg_combined)), 2)
    else:
        status = "insufficient_evidence"
        conf = 0.50

    return {
        "status": status,
        "confidence_score": conf,
        "signals": {
            "semantic_similarity": round(avg_semantic, 4),
            "domain_similarity": round(avg_domain, 4),
            "topic_similarity": round(avg_topic, 4),
            "audience_similarity": round(avg_audience, 4),
            "combined_score": round(avg_combined, 4)
        },
        "reason_codes": list(set(code for p in pairwise_results for code in p["reason_codes"]))
    }


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
  "summary": "Brief overall summary of what the Reel is about",
  "topic": "Main topic discussed or visually demonstrated",
  "content_category": "Category e.g. Educational, B2B Showcase, Travel, Entertainment, Lifestyle",
  "hook": "Visual or textual hook observed in opening frames",
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
  "observations": ["Evidence-based observation 1 grounded directly in frames/audio/caption", "Evidence-based observation 2"],
  "recommended_content_angle": "How a creator or business can adapt or recreate this content angle"
}"""

    prompt_text = (
        f"Reel Metadata:\n"
        f"- Source: {source_info}\n"
        f"- Video Duration: {duration} seconds\n"
        f"- Audio Stream Present: {'Yes' if has_audio else 'No (Silent Video)'}\n"
        f"- User Caption: {caption if caption else 'No caption provided.'}\n\n"
        f"CRITICAL: Keep analysis evidence-based. Do NOT invent details that cannot be derived from visual frames, audio stream, or caption.\n\n"
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
            uploader = info.get("uploader") or info.get("uploader_id") or info.get("channel") or ""

        if not uploader:
            match = re.search(r'(?:instagram\.com\/|tiktok\.com\/@|youtube\.com\/@)([a-zA-Z0-9_\.\-]+)', url)
            if match:
                uploader = f"@{match.group(1)}"

        if uploader and not uploader.startswith("@"):
            uploader = f"@{uploader}"

        return {
            "temp_dir": tmp_dir,
            "video_path": video_path,
            "title_caption": caption_text,
            "uploader_handle": uploader or None,
            "duration": info.get("duration")
        }
    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        logger.error(f"[URL] Failed to download Reel from URL: {e}")
        raise HTTPException(status_code=400, detail=f"Could not download video from provided URL: {str(e)}")


def process_single_url_sync(url: str, caption: Optional[str] = None) -> dict:
    """Helper to synchronously process a single Reel URL with exception handling."""
    try:
        reel_data = download_reel_from_url(url)
        temp_video_path = reel_data["video_path"]
        url_caption = reel_data["title_caption"]
        uploader_handle = reel_data.get("uploader_handle")
        
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
                "success": ai_result.get("success", False),
                "reel_url": url,
                "uploader_handle": uploader_handle,
                "duration_sec": frames_data.get("duration_sec"),
                "has_audio": frames_data.get("has_audio"),
                "frames_analyzed": frames_data.get("frame_count"),
                "effective_caption": effective_caption,
                "ai_analysis": ai_result,
                "error": ai_result.get("error") if not ai_result.get("success") else None
            }
        finally:
            shutil.rmtree(reel_data["temp_dir"], ignore_errors=True)
    except Exception as e:
        logger.error(f"[SINGLE_URL] Error processing {url}: {e}")
        return {
            "success": False,
            "reel_url": url,
            "error": str(e)
        }


def synthesize_batch_reel_intelligence(reels_results: list) -> dict:
    """
    Evaluates relationship between multiple Reels using programmatic similarity metrics BEFORE LLM explanation.
    Enforces Evidence > Forced Insights.
    """
    valid_reels = []
    for idx, r in enumerate(reels_results):
        if r.get("success") and r.get("ai_analysis", {}).get("success"):
            analysis = r["ai_analysis"].get("analysis")
            if isinstance(analysis, dict):
                valid_reels.append({
                    "reel_id": idx + 1,
                    "url": r.get("reel_url", f"Reel #{idx+1}"),
                    "analysis": analysis
                })

    if len(valid_reels) < 2:
        return {
            "relationship": {
                "status": "single_reel",
                "confidence_score": 1.0,
                "reason": "Fewer than 2 valid Reels were provided. Relationship check skipped.",
                "standalone_comparisons": None
            },
            "cross_reel_insights": None
        }

    # 1. Compute internal programmatic similarity evaluation
    prog_eval = evaluate_batch_pairwise_similarity(valid_reels)
    logger.info(f"[SIMILARITY_ENGINE] Programmatic pairwise evaluation result: {json.dumps(prog_eval)}")
    print(f"[SIMILARITY_ENGINE] Computed programmatic signals: status={prog_eval['status']}, combined_score={prog_eval['signals'].get('combined_score')}")

    prog_status = prog_eval["status"]
    prog_confidence = prog_eval["confidence_score"]
    reason_codes = prog_eval.get("reason_codes", [])

    summary_prompt = f"""You are an evidence-first senior social media content intelligence analyst.
Analyze the following JSON analyses extracted independently from {len(valid_reels)} different Reels:

{json.dumps(valid_reels, indent=2)}

PROGRAMMATIC EVIDENCE (Calculated mathematically by backend similarity engine):
- Programmatic Decision: {prog_status.upper()} (Confidence: {prog_confidence})
- Internal Reason Codes: {', '.join(reason_codes)}
- Internal Similarity Signals: {json.dumps(prog_eval['signals'])}

CRITICAL EVALUATION RULES:
1. YOU MUST ADHERE TO THE PROGRAMMATIC DECISION: "{prog_status}".
2. Explain this decision to the user in clear, professional natural language.
3. DO NOT output or reveal raw numerical similarity scores (like cosine similarity numbers, vectors, thresholds, weights, or math formulas) in the user-facing natural language text.
4. SIMILARITY DOES NOT AUTOMATICALLY MEAN CAUSATION.
   Sharing surface editing formats (like fast cuts or asking a question) does NOT make two Reels on completely different topics related.
5. IF PROGRAMMATIC STATUS IS "unrelated" OR "insufficient_evidence":
   - State explicitly in 'reason': "These Reels do not appear to be meaningfully related. They cover different topics, target different audiences, and have different content objectives. Therefore, no reliable cross-Reel pattern can be established from these inputs."
   - DO NOT generate forced cross-Reel patterns or insights.
   - Set all cross_reel_insights arrays to empty ([]).
   - Provide 'standalone_comparisons' highlighting how each Reel is strong in its own independent way.

6. IF PROGRAMMATIC STATUS IS "related":
   - Provide evidence-backed cross_reel_insights.
   - Explicitly distinguish between OBSERVED PATTERNS (facts visible across reels) and HYPOTHESES (cautious explanations for performance, NEVER presented as proven causation).

Return ONLY a JSON object matching this exact structure:
{{
  "relationship": {{
    "status": "{prog_status}",
    "confidence_score": {prog_confidence},
    "reason": "Detailed evidence-backed explanation of why these Reels are {prog_status}, adhering strictly to the programmatic findings.",
    "standalone_comparisons": "Short comparison showing how each Reel is strong in its own way (mandatory if unrelated/insufficient_evidence, optional if related)"
  }},
  "cross_reel_insights": {{
    "observed_patterns": ["Observed pattern 1 (Fact)", "Observed pattern 2"],
    "hypotheses_and_explanations": ["Hypothesis 1: Possible explanation for performance (explicitly noted as hypothesis)", "Hypothesis 2"],
    "shared_strengths": ["Shared strength 1"],
    "similar_hooks": ["Similar hook 1"],
    "common_audience_characteristics": "Summary of common target audience traits",
    "recurring_content_structures": ["Recurring structure 1"],
    "potential_content_opportunities": ["Opportunity 1 for creators/brands"]
  }}
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
        parsed = json.loads(clean_text.strip())

        # Attach internal debug metadata for developer logging/inspection
        parsed["_internal_debug"] = prog_eval
        print(f"[BATCH] Synthesis complete. Programmatic status: {prog_status} -> User explanation generated.")
        return parsed
    except Exception as e:
        logger.warning(f"[BATCH] Cross-Reel synthesis error: {e}")
        return {
            "relationship": {
                "status": prog_status,
                "confidence_score": prog_confidence,
                "reason": f"These Reels do not appear to be meaningfully related based on internal feature analysis. Reason signals: {', '.join(reason_codes)}.",
                "standalone_comparisons": "Each Reel has been analyzed independently above."
            },
            "cross_reel_insights": {
                "observed_patterns": [],
                "hypotheses_and_explanations": [],
                "shared_strengths": [],
                "similar_hooks": [],
                "common_audience_characteristics": "",
                "recurring_content_structures": [],
                "potential_content_opportunities": []
            },
            "_internal_debug": prog_eval
        }


def cluster_reels_by_content_direction(valid_reels: list, pairwise_eval: Optional[dict] = None) -> list:
    """
    Groups reference Reels into distinct Content Clusters / Directions.
    
    A Reel can:
    - belong to a cluster
    - belong to a different cluster
    - remain standalone if there is insufficient evidence to group it.
    
    Do NOT force every Reel into a single combined cluster.
    """
    if not valid_reels:
        return []

    reels_summaries = []
    for r in valid_reels:
        rid = r.get("id")
        handle = r.get("uploader_handle") or "Reel"
        analysis = r.get("analysis", {})
        topic = analysis.get("topic") or analysis.get("summary") or "General Content"
        category = analysis.get("content_category") or "General"
        audience = analysis.get("target_audience") or "General Audience"
        format_style = analysis.get("storytelling_format") or analysis.get("visual_style") or "Standard"
        intent = analysis.get("emotional_trigger") or "Educational"
        
        reels_summaries.append({
            "reel_id": rid,
            "handle": handle,
            "topic": topic,
            "category": category,
            "target_audience": audience,
            "format_style": format_style,
            "intent": intent,
            "summary": analysis.get("summary", "")
        })

    clustering_prompt = f"""You are a senior social media content strategist.
Analyze these {len(valid_reels)} reference Reels and group them into distinct, meaningful CONTENT CLUSTERS / DIRECTIONS.

REEL SUMMARIES:
{json.dumps(reels_summaries, indent=2)}

INTERNAL PROGRAMMATIC SIMILARITY SIGNAL (Supporting evidence only):
{json.dumps(pairwise_eval, indent=2) if pairwise_eval else "None"}

CRITICAL CLUSTERING RULES:
1. DO NOT force all Reels into one combined dataset if they belong to different content directions.
2. Group Reels based on:
   - Primary topic, subject domain (e.g. Business/Founder vs Marketing vs Local/Lifestyle vs Travel)
   - Target audience overlap
   - Content intent (e.g. Educational/Business vs Local/Atmospheric/Lifestyle)
3. Surface video editing styles (e.g. fast cuts, music overlays) must NOT force unrelated topics into the same cluster.
4. If a Reel does not share a clear, meaningful content direction with others, make it a STANDALONE cluster (is_standalone: true).
5. For grouped clusters (2+ Reels), provide 'why_together' explaining why they belong together (e.g., "Both focus on business/marketing education for a professional audience.").
6. For separated/standalone clusters, provide 'why_separate_explanation' explaining why it is separate from other clusters in the uploaded set (e.g., "Separated from the Business & Marketing group because this Reel is primarily atmospheric/local content and does not share a meaningful content direction with the business/marketing Reels.").

Return ONLY a JSON array of cluster objects matching this structure:
[
  {{
    "cluster_id": "direction_1",
    "cluster_name": "BUSINESS & MARKETING",
    "reel_ids": [1, 2],
    "relationship_type": "RELATED",
    "why_together": "Both focus on business/marketing education for a professional audience.",
    "why_separate_explanation": "Focuses on business leadership, founder advice, and client management.",
    "confidence": "high",
    "is_standalone": false
  }},
  {{
    "cluster_id": "direction_2",
    "cluster_name": "RAIPUR / LIFESTYLE",
    "reel_ids": [3],
    "relationship_type": "STANDALONE",
    "why_together": "",
    "why_separate_explanation": "This Reel is primarily atmospheric/local content and does not share a meaningful content direction with the business/marketing Reels.",
    "confidence": "high",
    "is_standalone": true
  }}
]"""

    try:
        resp = xkiro_client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": clustering_prompt}],
            temperature=0.1
        )
        clean_text = resp.choices[0].message.content.strip()
        if clean_text.startswith("```"):
            clean_text = clean_text.split("```")[1]
            if clean_text.startswith("json"):
                clean_text = clean_text[4:]
        clusters = json.loads(clean_text.strip())
        if isinstance(clusters, list) and len(clusters) > 0:
            print(f"[CLUSTERING] Formed {len(clusters)} content cluster(s).")
            return clusters
    except Exception as e:
        logger.warning(f"[CLUSTERING] LLM clustering failed, falling back to standalone grouping: {e}")

    # Fallback: standalone cluster per reel
    fallback_clusters = []
    for idx, r in enumerate(valid_reels):
        rid = r.get("id", idx + 1)
        analysis = r.get("analysis", {})
        topic = analysis.get("topic") or analysis.get("content_category") or f"Content Direction #{idx+1}"
        fallback_clusters.append({
            "cluster_id": f"direction_{idx+1}",
            "cluster_name": str(topic).upper(),
            "reel_ids": [rid],
            "relationship_type": "STANDALONE",
            "why_together": "",
            "why_separate_explanation": f"Independent content direction covering {topic}.",
            "confidence": "medium",
            "is_standalone": True
        })
    return fallback_clusters


def generate_content_learning_report(valid_reels: list, relationship_data: Optional[dict] = None, cross_insights: Optional[dict] = None) -> dict:
    """
    Generates a simple, accessible Content Learning report for business owners in plain English.
    Hides technical jargon, clustering terms, algorithms, and confidence metrics.
    """
    reel_count = len(valid_reels)
    if reel_count == 0:
        return {}

    # Perform internal content clustering / bifurcation
    clusters = cluster_reels_by_content_direction(valid_reels, relationship_data)

    # Format input summaries for report prompt
    formatted_reels_input = []
    for r in valid_reels:
        rid = r.get("id")
        handle = r.get("uploader_handle") or ""
        analysis = r.get("analysis", {})
        topic = analysis.get("topic") or analysis.get("summary") or "Content Topic"
        
        if handle and handle.strip():
            display_title = f"{handle.strip()} — {topic}"
        else:
            display_title = f"Reel {rid} — {topic}"

        formatted_reels_input.append({
            "id": rid,
            "display_title": display_title,
            "uploader_handle": handle or None,
            "topic": topic,
            "reel_url": r.get("reel_url"),
            "summary": analysis.get("summary"),
            "hook": analysis.get("hook"),
            "format": analysis.get("storytelling_format"),
            "observations": analysis.get("observations", [])
        })

    report_prompt = f"""You are a smart, friendly business advisor sitting down with a business owner.
They gave you {reel_count} Instagram Reels they saved as reference.
Your job is to explain what you noticed and what they could try in simple, everyday English.

STRICT WRITING RULES:
1. Write in plain, conversational English as if talking directly to a busy business owner.
2. ABSOLUTELY NO TECHNICAL JARGON OR ANALYTICS TERMINOLOGY (e.g. content clusters, semantic similarity, engagement potential).
3. ALWAYS refer to Reels using the handle and topic: e.g. "@thefrench3 — Founder & Client Relationship".
4. SEPARATE DIFFERENT TYPES OF CONTENT: Group Reels by meaningful business direction (e.g., "Client Acquisition" vs "General Growth").
5. USE THE SPECIFIC BUSINESS CONTEXT: Identify what kind of business these Reels are for (e.g., Therapist, Real Estate, E-commerce). Do NOT use generic phrases like "If you're creating business content...". Instead, adapt your advice to their actual field (e.g., "For a therapist, you could test...").
6. EXTRACT SPECIFIC PATTERNS, NOT GENERIC ONES: Instead of "Clear promises grab attention fast", observe what they actually do: "Most of these Reels tell the viewer exactly what they are going to get before the explanation begins." Provide a direct example from the Reels.
7. GIVE CONCRETE ACTIONS: Instead of "You should market yourself", notice specific actions like "They give the viewer a specific problem and then 3-5 things they can do about it." Provide specific 'what to try' examples tailored to their field.
8. NO UNSUPPORTED CLAIMS: Do not claim "People save or send Reels that do X" unless you have data. Use observable facts: "The Reels in this set frequently give the viewer a specific action rather than only explaining an idea."

REEL INFORMATION:
{json.dumps(formatted_reels_input, indent=2)}

INTERNAL CONTENT CATEGORIES IDENTIFIED:
{json.dumps(clusters, indent=2)}

Return ONLY a JSON object with this exact structure:
{{
  "summary_header": {{
    "title": "CONTENT LEARNINGS",
    "subtitle": "Here’s what stood out from the Reels you shared.",
    "description": "Here is a simple summary of what we noticed across your reference Reels and what you could test in your upcoming content."
  }},
  "what_these_reels_are_about": [
    {{
      "category_name": "Therapist Marketing / Client Acquisition",
      "summary_text": "Most of your references are about helping therapists grow their practice or social media presence.",
      "reels": [
        {{
          "display_title": "@Hannah Ciampini — getting clients quickly",
          "uploader_handle": "@Hannah Ciampini",
          "topic": "Getting clients quickly",
          "reel_url": "https://..."
        }}
      ],
      "note": ""
    }}
  ],
  "what_stood_out": [
    {{
      "title": "They tell the viewer what they will get immediately",
      "observation": "Most of these Reels don't start with general information. They start with a specific problem or outcome, like in @Hannah Ciampini's Reel where she says 'If you're a therapist who needs clients FAST...'."
    }}
  ],
  "what_you_can_try": [
    {{
      "title": "Try 1 — Turn a broad topic into a short list of specific actions",
      "what_to_try": "Instead of making a Reel called 'Tips for managing anxiety', try making it more specific by offering 3-5 things they can do about a specific problem.",
      "why_it_may_be_worth_trying": "The strongest common approach in these references is turning a broad topic into a short list of things someone can actually do.",
      "simple_example": "For example: '3 things to do when your mind won't stop overthinking at night.'"
    }}
  ],
  "what_we_dont_know_yet": "We can see these patterns in the Reels you shared, but we can't say yet that one format definitely performs better because we don't have enough comparable performance data.",
  "one_simple_takeaway": "For a therapist, you could test starting with a specific situation your clients commonly experience, rather than general advice."
}}"""

    try:
        resp = xkiro_client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": report_prompt}],
            temperature=0.2
        )
        clean_text = resp.choices[0].message.content.strip()
        if clean_text.startswith("```"):
            clean_text = clean_text.split("```")[1]
            if clean_text.startswith("json"):
                clean_text = clean_text[4:]
        report_data = json.loads(clean_text.strip())
        print(f"[BUSINESS_REPORT] Generated plain-English Content Learning Report for {reel_count} Reels.")
        return report_data
    except Exception as e:
        logger.warning(f"[BUSINESS_REPORT] Failed to generate report: {e}")
        return {
            "summary_header": {
                "title": "CONTENT LEARNINGS",
                "subtitle": "Here’s what stood out from the Reels you shared.",
                "description": "Here is a simple summary of what we noticed across your reference Reels."
            },
            "what_these_reels_are_about": [
                {
                    "category_name": "Reference Content",
                    "summary_text": f"Analyzed {reel_count} reference Reels.",
                    "reels": [
                        {
                            "display_title": (r.get("uploader_handle") or "Reel") + " — " + (r.get("analysis", {}).get("topic") or "Topic"),
                            "uploader_handle": r.get("uploader_handle"),
                            "topic": r.get("analysis", {}).get("topic") or "Topic",
                            "reel_url": r.get("reel_url")
                        } for r in valid_reels
                    ],
                    "note": ""
                }
            ],
            "what_stood_out": [
                {
                    "title": "Clear topics make videos easy to follow",
                    "observation": "Each Reel focused on a specific topic or visual setting, making it easy for viewers to understand."
                }
            ],
            "what_you_can_try": [
                {
                    "title": "Try 1 — Start with a clear question or problem",
                    "what_to_try": "Open your next Reel by stating a problem your audience faces.",
                    "why_it_may_be_worth_trying": "A clear opening problem grabs viewer attention.",
                    "simple_example": "For example: 'Here is 1 mistake most business owners make...'"
                }
            ],
            "what_we_dont_know_yet": "We can see these patterns in the Reels you shared, but we can't say yet that one format definitely performs better because we don't have enough comparable performance data.",
            "one_simple_takeaway": "Focus on turning everyday problems into short, simple Reels."
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

        # Separate successful and failed Reel results
        successful_reels = [r for r in results if r.get("success")]
        print(f"[BATCH] Processed {len(successful_reels)} / {len(url_list)} Reel URLs successfully.")

        if not successful_reels:
            raise HTTPException(status_code=400, detail="Failed to process any of the provided Reel links. Please verify the URLs and try again.")

        # Build formatted reels list for response
        reels_payload = []
        for idx, r in enumerate(results):
            if r.get("success"):
                reels_payload.append({
                    "id": idx + 1,
                    "source": f"Reel URL: {r.get('reel_url')}",
                    "reel_url": r.get("reel_url"),
                    "uploader_handle": r.get("uploader_handle"),
                    "success": True,
                    "duration_sec": r.get("duration_sec"),
                    "has_audio": r.get("has_audio"),
                    "frames_analyzed": r.get("frames_analyzed"),
                    "analysis": r.get("ai_analysis", {}).get("analysis")
                })
            else:
                reels_payload.append({
                    "id": idx + 1,
                    "source": f"Reel URL: {r.get('reel_url')}",
                    "reel_url": r.get("reel_url"),
                    "success": False,
                    "error": r.get("error", "Failed to download or analyze video.")
                })

        # Synthesize cross-reel intelligence if 2 or more succeeded
        relationship_data = None
        cross_insights_data = None

        if len(successful_reels) >= 2:
            synthesis = await asyncio.to_thread(synthesize_batch_reel_intelligence, results)
            relationship_data = synthesis.get("relationship")
            cross_insights_data = synthesis.get("cross_reel_insights")
        else:
            relationship_data = {
                "status": "single_reel",
                "confidence_score": 1.0,
                "reason": "Only 1 Reel was successfully analyzed. Relationship comparison skipped.",
                "standalone_comparisons": None
            }

        # Generate Business Content Learning Report
        valid_reels_for_report = [r for r in reels_payload if r.get("success")]
        content_learnings = await asyncio.to_thread(
            generate_content_learning_report,
            valid_reels_for_report,
            relationship_data,
            cross_insights_data
        )

        return {
            "status": "success",
            "message": f"Successfully analyzed {len(successful_reels)} of {len(url_list)} Reels!",
            "batch_count": len(url_list),
            "reels": reels_payload,
            "relationship": relationship_data,
            "cross_reel_insights": cross_insights_data,
            "content_learnings": content_learnings,
            "ai_analysis": {
                "success": True,
                "model": MODEL_NAME,
                "analysis": cross_insights_data,
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

            single_reel = {
                "id": 1,
                "source": source_info,
                "filename": file.filename,
                "success": ai_result.get("success", False),
                "duration_sec": frames_data.get("duration_sec"),
                "has_audio": frames_data.get("has_audio"),
                "frames_analyzed": frames_data.get("frame_count"),
                "analysis": ai_result.get("analysis") if ai_result.get("success") else None,
                "error": ai_result.get("error") if not ai_result.get("success") else None
            }

            content_learnings = await asyncio.to_thread(
                generate_content_learning_report,
                [single_reel] if single_reel.get("success") else [],
                None,
                None
            )

            return {
                "status": "success",
                "message": "Reel multimodal analysis complete!",
                "batch_count": 1,
                "reels": [single_reel],
                "relationship": None,
                "cross_reel_insights": None,
                "content_learnings": content_learnings,
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
        
        single_reel = {
            "id": 1,
            "source": f"Reel URL: {target_url}",
            "reel_url": target_url,
            "success": res.get("success", False),
            "duration_sec": res.get("duration_sec"),
            "has_audio": res.get("has_audio"),
            "frames_analyzed": res.get("frames_analyzed"),
            "analysis": res.get("ai_analysis", {}).get("analysis") if res.get("success") else None,
            "error": res.get("error") if not res.get("success") else None
        }

        if not res.get("success"):
            raise HTTPException(status_code=400, detail=res.get("error", "Failed to download or analyze video URL."))

        content_learnings = await asyncio.to_thread(
            generate_content_learning_report,
            [single_reel] if single_reel.get("success") else [],
            None,
            None
        )

        return {
            "status": "success",
            "message": "Reel URL fetched and analyzed successfully!",
            "batch_count": 1,
            "reels": [single_reel],
            "relationship": None,
            "cross_reel_insights": None,
            "content_learnings": content_learnings,
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


from pydantic import BaseModel
from typing import Any

class ChatRequest(BaseModel):
    message: str
    reels_context: list[Any]
    report_context: dict[Any, Any]

@app.post("/api/chat")
async def chat_about_reels(request: ChatRequest):
    """
    Allows the user to ask questions specifically about the analyzed Reels.
    Uses the provided reel analyses and the final report as context.
    """
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    system_prompt = f"""You are an insightful content strategy assistant specifically focused on helping a business owner understand their reference Reels.
The user will ask questions about the Reels they provided. Use the context below to answer.

CONTEXT:
--- Analyzed Reels ---
{json.dumps(request.reels_context, indent=2)}

--- Generated Content Learnings Report ---
{json.dumps(request.report_context, indent=2)}

STRICT RULES:
1. ONLY answer based on the provided Reels. Do not give generic social media advice.
2. Be direct and insightful. Reference specific Reels (by handle and topic) to support your points.
3. If the user asks for examples or ideas for their business, extract the underlying principle from the Reels (e.g., 'Turn a broad topic into a short list') and apply it to their business.
4. Keep answers relatively concise and conversational."""

    try:
        resp = xkiro_client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": request.message}
            ],
            temperature=0.3
        )
        reply = resp.choices[0].message.content.strip()
        return {"status": "success", "reply": reply}
    except Exception as e:
        logger.error(f"[CHAT] Error calling LLM: {e}")
        raise HTTPException(status_code=500, detail="Failed to get chat response.")

