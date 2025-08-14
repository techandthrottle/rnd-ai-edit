import google.generativeai as genai
import json
import re
from datetime import timedelta
import os
import subprocess
import logging
import time

def parse_srt(srt_content):
    blocks = srt_content.strip().split('\n\n')
    parsed_srt = []
    for block in blocks:
        lines = block.split('\n')
        if len(lines) >= 3:
            try:
                index = int(lines[0])
                time_str = lines[1]
                text = " ".join(lines[2:])

                start_time_str, end_time_str = time_str.split(' --> ')
                start_time = srt_time_to_seconds(start_time_str)
                end_time = srt_time_to_seconds(end_time_str)

                parsed_srt.append({
                    "index": index,
                    "start": start_time,
                    "end": end_time,
                    "text": text
                })
            except ValueError:
                # Skip malformed blocks
                continue
    return parsed_srt

def srt_time_to_seconds(time_str):
    parts = time_str.replace(',', '.').split(':')
    hours = float(parts[0])
    minutes = float(parts[1])
    seconds = float(parts[2])
    return hours * 3600 + minutes * 60 + seconds

def classify_content(srt_content):
    model = genai.GenerativeModel('gemini-2.5-pro')
    prompt = f"""Analyze the following SRT content and determine if it's a Podcast or a Short-form video.

A Podcast is typically long-form audio content with multiple topics, while a Short-form video is a short video with a single topic.

If it is a Podcast, identify the timestamp where a specific topic is being discussed. The output should be a JSON object with the following format:
{{
  "type": "Podcast",
  "topics": [
    {{
      "timestamp": "HH:MM:SS",
      "topic": "Topic description"
    }}
  ]
}}

If it is a Short-form video, just return the topic. The output should be a JSON object with the following format:
{{
  "type": "Short-form",
  "topic": "Topic description"
}}

SRT Content:
{srt_content}
"""
    response = model.generate_content(prompt)
    classification_text = response.text.strip()
    if "```json" in classification_text:
        json_start = classification_text.find('{')
        json_end = classification_text.rfind('}') + 1
        classification_json_str = classification_text[json_start:json_end]
    else:
        classification_json_str = classification_text

    classification = json.loads(classification_json_str)
    return classification

def detect_filler_words(video_path):
    temp_audio_path = "temp_audio.mp3"
    try:
        command = [
            "ffmpeg",
            "-i", video_path,
            "-q:a", "0",
            "-map", "a",
            temp_audio_path
        ]
        subprocess.run(command, check=True, capture_output=True, text=True)

        audio_file = genai.upload_file(path=temp_audio_path)
        while audio_file.state.name == "PROCESSING":
            time.sleep(2)
            audio_file = genai.get_file(audio_file.name)

        if audio_file.state.name == "FAILED":
            raise ValueError("Audio file processing failed.")

        model = genai.GenerativeModel('gemini-2.5-pro')
        prompt = f"""You are an expert video editor's assistant. Your task is to analyze this audio file and identify filler words that can be safely removed.

**CRITICAL INSTRUCTIONS:**
1.  **Analyze Acoustic Cues:** Listen for vocal hesitations, unnatural pauses, and verbal tics (e.g., \"um,\" \"uh,\" \"ah\"). Pay attention to the speaker's tone and pacing. A word like \"like\" might be a filler if it's said quickly with a hesitant tone, but not if it's part of a clear, confident statement.
2.  **Return JSON Output ONLY:** Your entire output must be ONLY the JSON object, with no additional text, explanations, or markdown formatting like ```json. The response should be immediately parsable as JSON. The object must contain a single key, \"filler_words\", which is a list of all the filler words you found. Each item must have the following structure:
    - `word`: The identified filler word.
    - `start`: The start time in \"HH:MM:SS.ms\" format.
    - `end`: The end time in \"HH:MM:SS.ms\" format.
    - `can_be_removed`: A boolean (`true` or `false`).
    - `reasoning`: A brief explanation for your decision based on both the word and its acoustic delivery.

**EXAMPLE OF THE ONLY VALID OUTPUT FORMAT:**
{{ "filler_words": [ {{ "word": \"um\", "start": \"00:00:01.234\", "end": \"00:00:01.567\", "can_be_removed": true, "reasoning": \"Hesitation before making a point.\" }} ] }}
"""
        response = model.generate_content([prompt, audio_file])
        response_text = response.text.strip()
        json_match = re.search(r'```json\n(.*?)\n```', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            if json_start != -1 and json_end != -1:
                json_str = response_text[json_start:json_end]
            else:
                logging.error(f"Could not find JSON in the response: {response_text}")
                return []

        try:
            result = json.loads(json_str)
            return result.get("filler_words", [])
        except json.JSONDecodeError as e:
            logging.error(f"Error decoding JSON from filler word detection response: {e}")
            logging.error(f"Invalid JSON string: {json_str}")
            # Attempt to fix the JSON by adding missing commas
            fixed_json_str = re.sub(r'}\s*{', '},{', json_str)
            try:
                result = json.loads(fixed_json_str)
                logging.info("Successfully repaired JSON by adding missing commas.")
                return result.get("filler_words", [])
            except json.JSONDecodeError:
                logging.error("Failed to repair JSON by adding commas. Trying to repair with LLM.")
                # Attempt to repair the JSON
                repair_prompt = f"The following JSON is invalid. Please fix it and return only the corrected JSON.\n\n{json_str}"
                repair_response = model.generate_content(repair_prompt)
                repaired_json_str = repair_response.text.strip()
                try:
                    result = json.loads(repaired_json_str)
                    return result.get("filler_words", [])
                except json.JSONDecodeError as e2:
                    logging.error(f"Failed to repair JSON: {e2}")
                    logging.error(f"Repaired JSON string: {repaired_json_str}")
                    return []

    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logging.error(f"Error during filler word detection: {e}")
        return []
    finally:
        if os.path.exists(temp_audio_path):
            os.remove(temp_audio_path)

def detect_silence_with_gemini(video_path):
    try:
        video_file = genai.upload_file(path=video_path)
        while video_file.state.name == "PROCESSING":
            time.sleep(10)
            video_file = genai.get_file(video_file.name)

        if video_file.state.name == "FAILED":
            raise ValueError("Video file processing failed.")

        model = genai.GenerativeModel('gemini-2.5-pro')
        prompt = f"""You are an expert video editor's assistant. Your task is to analyze this video file and identify all silent intervals that should be removed.

**CRITICAL INSTRUCTIONS:**
1.  **Analyze Video and Audio:** Pay attention to both the audio track and the visual elements.
2.  **Be Aggressive:** Prioritize a tight edit.
3.  **No Dialogue = Removal:** A segment should be considered for removal if there is no spoken dialogue, even if there is background noise, movement, or breathing.
4.  **Remove Gaps:** Remove any non-speaking gap longer than 0.5 seconds.
5.  **Action without Words:** Pay close attention to removing segments that contain action without words.
6.  **Return JSON Output:** Your final output must be a single, valid JSON object containing a list of all the silent intervals you found. Each item must have the following structure:
    - `start`: The start time in seconds (float).
    - `end`: The end time in seconds (float).

**EXAMPLE OUTPUT:**
```json
{{
  "silent_intervals": [
    {{
      "start": 1.2,
      "end": 2.5
    }},
    {{
      "start": 5.7,
      "end": 6.3
    }}
  ]
}}
"""
        response = model.generate_content([prompt, video_file], request_options={"timeout": 1200})
        response_text = response.text.strip()
        logging.info(f"SMART SILENCE RESPONSE: {response_text}")
        json_match = re.search(r'```json\n(.*?)\n```', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            if json_start != -1 and json_end != -1:
                json_str = response_text[json_start:json_end]
            else:
                logging.error(f"Could not find JSON in the response: {response_text}")
                return []

        try:
            result = json.loads(json_str)
            return result.get("silent_intervals", [])
        except json.JSONDecodeError as e:
            logging.error(f"Error decoding JSON from silence detection response: {e}")
            logging.error(f"Invalid JSON string: {json_str}")
            return []

    except Exception as e:
        logging.error(f"Error during silence detection: {e}")
        return []

def classify_silence(video_path, srt_content, silence_start_str, silence_end_str):
    parsed_srt = parse_srt(srt_content)

    silence_start = timedelta_string_to_seconds(silence_start_str)
    silence_end = timedelta_string_to_seconds(silence_end_str)

    context_before = ""
    context_after = ""

    for i in range(len(parsed_srt) - 1, -1, -1):
        if parsed_srt[i]["end"] < silence_start:
            context_before = parsed_srt[i]["text"]
            break

    for i in range(len(parsed_srt)):
        if parsed_srt[i]["start"] > silence_end:
            context_after = parsed_srt[i]["text"]
            break

    temp_clip_path = f"temp_clip_{{silence_start}}_{{silence_end}}.mp4"
    from utils.ffmpeg_utils import extract_clip
    if not extract_clip(video_path, silence_start, silence_end, temp_clip_path):
        logging.error("Failed to extract clip for silence classification.")
        return "unknown"

    try:
        video_file = genai.upload_file(path=temp_clip_path)
        while video_file.state.name == "PROCESSING":
            time.sleep(2)
            video_file = genai.get_file(video_file.name)

        if video_file.state.name == "FAILED":
            raise ValueError("Video clip processing failed.")

        model = genai.GenerativeModel('gemini-2.5-pro')
        prompt = f'''Analyze the following video clip, which is a silent pause in a larger video. The pause is {silence_end - silence_start} seconds long. The words spoken immediately before the pause were: '{context_before}'. The words spoken immediately after were: '{context_after}'.

Based on the visual and semantic context, decide if this pause is awkward 'dead air' that should be removed or if it is an intentional, meaningful pause that adds to the video's quality.

**CRITICAL INSTRUCTIONS:**
1.  **Be Aggressive:** Prioritize a tight edit.
2.  **No Dialogue = Removal:** A segment should be considered for removal if there is no spoken dialogue, even if there is background noise, movement, or breathing.
3.  **Remove Gaps:** Remove any non-speaking gap longer than 0.5 seconds.
4.  **Action without Words:** Pay close attention to removing segments that contain action without words.

Respond with 'REMOVE' if it should be cut, and 'KEEP' if it should be preserved.'''
        response = model.generate_content([prompt, video_file])
        classification = response.text.strip().lower()
        logging.info(f"SMART SILENCE RESPONSE: {classification}")
        if "remove" in classification:
            return "dead air"
        elif "keep" in classification:
            return "pause"
        else:
            return "unknown"
    finally:
        if os.path.exists(temp_clip_path):
            os.remove(temp_clip_path)

def suggest_b_roll(srt_content):
    model = genai.GenerativeModel('gemini-2.5-pro')
    prompt = f"""You are an expert video editor. Analyze the following SRT content and suggest B-roll footage to enhance the video.

Identify key moments, concepts, or keywords in the transcript that would benefit from illustrative B-roll.

For each suggestion, provide the timestamp from the SRT file and a brief, descriptive suggestion for the B-roll shot.

The output should be a JSON object with a single key "b_roll_suggestions" containing a list of suggestion objects. Each object should have the following format:
{{
  "timestamp": "HH:MM:SS",
  "suggestion": "A descriptive suggestion for the B-roll shot."
}}

SRT Content:
{srt_content}
"""
    response = model.generate_content(prompt)
    response_text = response.text.strip()
    if "```json" in response_text:
        json_start = response_text.find('{')
        json_end = response_text.rfind('}') + 1
        json_str = response_text[json_start:json_end]
    else:
        json_str = response_text

    try:
        result = json.loads(json_str)
        return result.get("b_roll_suggestions", [])
    except json.JSONDecodeError:
        logging.error(f"Error decoding JSON from B-roll suggestion response: {response_text}")
        return []

def detect_retakes(srt_content):
    model = genai.GenerativeModel('gemini-2.5-pro')
    prompt = f"""You are an expert video editor's assistant. Your task is to analyze the following SRT transcript and identify any re-takes or repeated phrases that should be removed to make the content more concise.

**CRITICAL INSTRUCTIONS:**
1.  **Identify Re-takes:** Look for instances where the speaker stumbles, pauses, and then repeats a phrase, often with a slight correction.
2.  **Identify Repeated Phrases:** Find phrases or sentences that are repeated verbatim or nearly verbatim without adding new information.
3.  **Return JSON Output ONLY:** Your entire output must be ONLY a valid JSON object. The object must contain a single key, "retakes_to_remove", which is a list of all the segments you identified for removal. Each item must have the following structure:
    - `start`: The start time in seconds (float) of the segment to remove.
    - `end`: The end time in seconds (float) of the segment to remove.
    - `reasoning`: A brief explanation for why this segment should be removed (e.g., "Re-take of the previous phrase.", "Unnecessary repetition.").

**EXAMPLE OF THE ONLY VALID OUTPUT FORMAT:**
{{
  "retakes_to_remove": [
    {{
      "start": 10.5,
      "end": 12.1,
      "reasoning": "Speaker stumbled and restarted the sentence."
    }},
    {{
      "start": 25.2,
      "end": 28.0,
      "reasoning": "This phrase was already stated clearly earlier."
    }}
  ]
}}

SRT Content:
{srt_content}
"""
    response = model.generate_content(prompt)
    response_text = response.text.strip()
    
    json_match = re.search(r'```json\n(.*?)\n```', response_text, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)
    else:
        json_start = response_text.find('{')
        json_end = response_text.rfind('}') + 1
        if json_start != -1 and json_end != -1:
            json_str = response_text[json_start:json_end]
        else:
            logging.error(f"Could not find JSON in the response for retakes: {response_text}")
            return []

    try:
        result = json.loads(json_str)
        return result.get("retakes_to_remove", [])
    except json.JSONDecodeError as e:
        logging.error(f"Error decoding JSON from retake detection response: {e}")
        logging.error(f"Invalid JSON string: {json_str}")
        return []