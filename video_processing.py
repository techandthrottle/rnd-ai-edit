
import os
import requests
from urllib.parse import urlparse
import logging
import json
from utils.ffmpeg_utils import detect_silence, get_video_metadata, apply_noise_reduction, cut_video_segments, timedelta_string_to_seconds, burn_srt_to_video
from services.transcription_service import transcribe_video
from services.classification_service import classify_content, classify_silence, detect_filler_words

def download_video(task_id, video_url, video_path, task_status):
    task_status[task_id].update({"status": "DOWNLOADING", "progress": 10, "message": f"Attempting to download video from: {video_url}"})
    logging.info(f"[{task_id}] Attempting to download video from: {video_url}")
    with requests.get(video_url, stream=True) as r:
        r.raise_for_status()
        with open(video_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    task_status[task_id].update({"status": "DOWNLOADED", "progress": 20, "message": f"Video downloaded successfully to: {video_path}"})
    logging.info(f"[{task_id}] Video downloaded successfully to: {video_path}")

def apply_noise_reduction_step(task_id, video_path, recipe, task_status):
    if recipe.get("apply_noise_reduction", False):
        noise_reduced_video_path = os.path.splitext(video_path)[0] + "_nr.mp4"
        if apply_noise_reduction(video_path, noise_reduced_video_path, task_id, task_status):
            return noise_reduced_video_path
        else:
            logging.warning(f"[{task_id}] Noise reduction failed or was skipped, continuing with original video.")
    return video_path

def get_metadata_step(task_id, video_path, task_status):
    task_status[task_id].update({"status": "GETTING_METADATA", "progress": 45, "message": "Getting video metadata..."})
    logging.info(f"[{task_id}] Getting video metadata for: {video_path}")
    video_metadata = get_video_metadata(video_path)
    source_aspect_ratio = video_metadata.get("aspect_ratio")
    video_duration = video_metadata.get("duration")
    logging.info(f"[{task_id}] Source video aspect ratio: {source_aspect_ratio}, Duration: {video_duration} seconds")
    available_aspect_ratios = []
    if source_aspect_ratio == "16:9":
        available_aspect_ratios.extend(["16:9", "9:16"])
    elif source_aspect_ratio == "9:16":
        available_aspect_ratios.append("9:16")
    else:
        available_aspect_ratios.append(source_aspect_ratio)
    task_status[task_id].update({"status": "METADATA_COMPLETE", "progress": 50, "message": f"Available aspect ratios: {available_aspect_ratios}"})
    logging.info(f"[{task_id}] Available aspect ratios: {available_aspect_ratios}")
    return video_metadata, available_aspect_ratios

def transcribe_step(task_id, video_path, recipe, srt_path, task_status):
    if recipe.get("transcribe", False):
        task_status[task_id].update({"status": "TRANSCRIBING", "progress": 60, "message": "Transcribing video..."})
        logging.info(f"[{task_id}] Transcribing video: {video_path}")
        srt_content = transcribe_video(video_path)
        if srt_content is None:
            task_status[task_id].update({"status": "FAILED", "progress": 70, "message": "Transcription failed."})
            logging.error(f"[{task_id}] Transcription failed, returned None.")
            return None
        task_status[task_id].update({"status": "TRANSCRIPTION_COMPLETE", "progress": 70, "message": "Video transcription complete."})
        logging.info(f"[{task_id}] Video transcription complete.")
        task_status[task_id].update({"status": "SAVING_SRT", "progress": 75, "message": f"Saving SRT to file: {srt_path}"})
        logging.info(f"[{task_id}] Saving SRT to file: {srt_path}")
        with open(srt_path, 'w', encoding='utf-8') as f:
            f.write(srt_content)
        task_status[task_id].update({"status": "SRT_SAVED", "progress": 80, "message": "SRT file saved."})
        logging.info(f"[{task_id}] SRT file saved.")
        return srt_content
    return None

def detect_silence_step(task_id, video_path, recipe, task_status):
    if recipe.get("detect_silence", False):
        task_status[task_id].update({"status": "DETECTING_SILENCE", "progress": 85, "message": "Detecting silence..."})
        logging.info(f"[{task_id}] Detecting silence in video: {video_path}")
        silence_intervals = detect_silence(video_path)
        task_status[task_id].update({"status": "SILENCE_DETECTION_COMPLETE", "progress": 90, "message": f"Silence detection complete. Found {len(silence_intervals)} intervals."})
        logging.info(f"[{task_id}] Silence detection complete. Found {len(silence_intervals)} intervals.")
        return silence_intervals
    return []

def classify_content_step(task_id, srt_content, recipe, task_status):
    if recipe.get("classify_content", False) and srt_content:
        task_status[task_id].update({"status": "CLASSIFYING_CONTENT", "progress": 92, "message": "Classifying content..."})
        logging.info(f"[{task_id}] Classifying content.")
        classification = classify_content(srt_content)
        task_status[task_id].update({"status": "CONTENT_CLASSIFICATION_COMPLETE", "progress": 94, "message": f"Content classification complete: {classification}"})
        logging.info(f"[{task_id}] Content classification complete: {classification}")
        return classification
    return None

def classify_silence_step(task_id, srt_content, silence_intervals, recipe, task_status):
    if recipe.get("classify_silence", False) and srt_content and silence_intervals:
        task_status[task_id].update({"status": "CLASSIFYING_SILENCE", "progress": 96, "message": "Classifying silence intervals..."})
        logging.info(f"[{task_id}] Classifying silence intervals.")
        classified_silence_intervals = []
        for interval in silence_intervals:
            silence_type = classify_silence(srt_content, interval["start"], interval["end"])
            classified_silence_intervals.append({"start": interval["start"], "end": interval["end"], "type": silence_type})
        task_status[task_id].update({"status": "SILENCE_CLASSIFICATION_COMPLETE", "progress": 98, "message": "Silence classification complete."})
        logging.info(f"[{task_id}] Silence classification complete.")
        return classified_silence_intervals
    return []

def detect_filler_words_step(task_id, video_path, recipe, task_status):
    if recipe.get("detect_filler_words", False):
        task_status[task_id].update({"status": "DETECTING_FILLER_WORDS", "progress": 99, "message": "Detecting filler words from audio..."})
        logging.info(f"[{task_id}] Detecting filler words from audio: {video_path}")
        filler_words_detected = detect_filler_words(video_path)
        task_status[task_id].update({"status": "FILLER_WORD_DETECTION_COMPLETE", "progress": 100, "message": f"Filler word detection complete. Found {len(filler_words_detected)} filler words."})
        logging.info(f"[{task_id}] Filler word detection complete. Found {len(filler_words_detected)} filler words.")
        return filler_words_detected
    return []

def cut_video_step(task_id, video_path, classified_silence_intervals, filler_words_detected, video_duration, recipe, task_status):
    if recipe.get("cut_video", False):
        task_status[task_id].update({"status": "PREPARING_CUTS", "progress": 99, "message": "Preparing video cuts..."})
        logging.info(f"[{task_id}] Preparing video cuts.")
        intervals_to_remove = []
        if recipe.get("remove_silence", False):
            for interval in classified_silence_intervals:
                start_sec = timedelta_string_to_seconds(interval["start"])
                end_sec = timedelta_string_to_seconds(interval["end"])
                intervals_to_remove.append({"start": start_sec, "end": end_sec})
        if recipe.get("remove_filler_words", False):
            for filler_word in filler_words_detected:
                if filler_word["can_be_removed"]:
                    start_sec = timedelta_string_to_seconds(filler_word["start"])
                    end_sec = timedelta_string_to_seconds(filler_word["end"])
                    intervals_to_remove.append({"start": start_sec, "end": end_sec})
        if intervals_to_remove:
            intervals_to_remove.sort(key=lambda x: x["start"])
            merged_intervals_to_remove = []
            if intervals_to_remove:
                current_interval = intervals_to_remove[0]
                for i in range(1, len(intervals_to_remove)):
                    next_interval = intervals_to_remove[i]
                    if next_interval["start"] <= current_interval["end"]:
                        current_interval["end"] = max(current_interval["end"], next_interval["end"])
                    else:
                        merged_intervals_to_remove.append(current_interval)
                        current_interval = next_interval
                merged_intervals_to_remove.append(current_interval)
            segments_to_keep = []
            current_time = 0.0
            for interval_to_remove in merged_intervals_to_remove:
                if current_time < interval_to_remove["start"]:
                    segments_to_keep.append({"start": current_time, "end": interval_to_remove["start"]})
                current_time = max(current_time, interval_to_remove["end"])
            if current_time < video_duration:
                segments_to_keep.append({"start": current_time, "end": video_duration})
            trimmed_video_path = os.path.splitext(video_path)[0] + "_trimmed.mp4"
            task_status[task_id].update({"status": "CUTTING_VIDEO", "progress": 99, "message": "Cutting video segments..."})
            logging.info(f"[{task_id}] Cutting video segments to: {trimmed_video_path}")
            if cut_video_segments(video_path, segments_to_keep, trimmed_video_path):
                logging.info("Video cutting complete.")
                return trimmed_video_path
            else:
                logging.warning("Video cutting failed or was skipped.")
    return video_path

def burn_captions_step(task_id, video_path, recipe, task_status):
    if recipe.get("burn_captions", False):
        task_status[task_id].update({"status": "RETRANSCRIBING_TRIMMED_VIDEO", "progress": 99, "message": "Re-transcribing trimmed video..."})
        logging.info(f"[{task_id}] Re-transcribing trimmed video: {video_path}")
        trimmed_srt_content = transcribe_video(video_path)
        trimmed_srt_path = os.path.splitext(video_path)[0] + ".srt"
        with open(trimmed_srt_path, 'w', encoding='utf-8') as f:
            f.write(trimmed_srt_content)
        logging.info(f"[{task_id}] Trimmed SRT saved to: {trimmed_srt_path}")
        task_status[task_id].update({"status": "BURNING_CAPTIONS", "progress": 99, "message": "Burning captions to video..."})
        logging.info(f"[{task_id}] Burning captions to video: {video_path}")
        final_video_path = os.path.splitext(video_path)[0] + "_captioned.mp4"
        ass_style = recipe.get("ass_style")
        if burn_srt_to_video(video_path, trimmed_srt_path, final_video_path, ass_style=ass_style):
            logging.info("Captions burned to video successfully.")
            return final_video_path
        else:
            logging.warning("Burning captions failed or was skipped.")
    return video_path

def process_video_with_recipe(task_id, video_url, recipe, task_status):
    task_status[task_id] = {"status": "PENDING", "progress": 0, "message": "Starting video processing..."}

    video_filename = os.path.basename(urlparse(video_url).path) if os.path.basename(urlparse(video_url).path) else "input.mp4"
    video_path = video_filename
    srt_path = os.path.splitext(video_path)[0] + ".srt"

    try:
        download_video(task_id, video_url, video_path, task_status)
        video_path = apply_noise_reduction_step(task_id, video_path, recipe, task_status)
        video_metadata, available_aspect_ratios = get_metadata_step(task_id, video_path, task_status)
        video_duration = video_metadata.get("duration")
        srt_content = transcribe_step(task_id, video_path, recipe, srt_path, task_status)
        if srt_content is None and recipe.get("transcribe", False):
            return # Stop processing if transcription failed

        silence_intervals = detect_silence_step(task_id, video_path, recipe, task_status)
        classification = classify_content_step(task_id, srt_content, recipe, task_status)
        classified_silence_intervals = classify_silence_step(task_id, srt_content, silence_intervals, recipe, task_status)
        filler_words_detected = detect_filler_words_step(task_id, video_path, recipe, task_status)
        video_path = cut_video_step(task_id, video_path, classified_silence_intervals, filler_words_detected, video_duration, recipe, task_status)
        video_path = burn_captions_step(task_id, video_path, recipe, task_status)

        absolute_path = os.path.abspath(srt_path) if srt_content else None
        final_absolute_path = os.path.abspath(video_path)
        task_status[task_id].update({
            "status": "COMPLETED",
            "progress": 100,
            "message": "Video processing completed successfully!",
            "result": {
                "srt_path": absolute_path,
                "final_video_path": final_absolute_path,
                "classification": classification,
                "silence_intervals": classified_silence_intervals,
                "filler_words": filler_words_detected,
                "available_aspect_ratios": available_aspect_ratios
            }
        })
        logging.info(f"[{task_id}] Video processing completed successfully.")

    except requests.exceptions.RequestException as e:
        task_status[task_id].update({"status": "FAILED", "message": f"Failed to download video: {str(e)}", "error": str(e)})
        logging.error(f"[{task_id}] Failed to download video: {e}", exc_info=True)
    except Exception as e:
        task_status[task_id].update({"status": "FAILED", "message": f"An unexpected error occurred: {str(e)}", "error": str(e)})
        logging.error(f"[{task_id}] An unexpected error occurred: {e}", exc_info=True)
