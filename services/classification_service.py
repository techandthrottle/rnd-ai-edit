import google.generativeai as genai
import json
import re
from datetime import timedelta
import os
import subprocess
import logging

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
        model = genai.GenerativeModel('gemini-2.5-pro')
        prompt = f"""You are an expert video editor's assistant. Your task is to analyze this audio file and identify filler words that can be safely removed.

**CRITICAL INSTRUCTIONS:**
1.  **Analyze Acoustic Cues:** Listen for vocal hesitations, unnatural pauses, and verbal tics (e.g., "um," "uh," "ah"). Pay attention to the speaker's tone and pacing. A word like "like" might be a filler if it's said quickly with a hesitant tone, but not if it's part of a clear, confident statement.
2.  **Return JSON Output:** Your final output must be a single, valid JSON object containing a list of all the filler words you found. Each item must have the following structure:
    - `word`: The identified filler word.
    - `start`: The start time in "HH:MM:SS.ms" format.
    - `end`: The end time in "HH:MM:SS.ms" format.
    - `can_be_removed`: A boolean (`true` or `false`).
    - `reasoning`: A brief explanation for your decision based on both the word and its acoustic delivery.

"""
        response = model.generate_content([prompt, audio_file])
        response_text = response.text.strip()
        if "```json" in response_text:
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            json_str = response_text[json_start:json_end]
        else:
            json_str = response_text

        result = json.loads(json_str)
        return result.get("filler_words", [])

    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError) as e:
        logging.error(f"Error during filler word detection: {e}")
        return []
    finally:
        if os.path.exists(temp_audio_path):
            os.remove(temp_audio_path)

def classify_silence(srt_content, silence_start_str, silence_end_str):
    parsed_srt = parse_srt(srt_content)

    def timedelta_string_to_seconds(td_str):
        parts = td_str.split(':')
        h = float(parts[0])
        m = float(parts[1])
        s = float(parts[2])
        return h * 3600 + m * 60 + s

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

    model = genai.GenerativeModel('gemini-2.5-pro')
    prompt = f"""Given the following context, classify the type of silence that occurs between the 'Text Before Silence' and 'Text After Silence'.

Classify the silence as one of the following: "pause", "dead air", or "scene change".
- A "pause" is a short, natural break in speech.
- "Dead air" is a longer, unnatural silence where speech is expected.
- "Scene change" indicates a transition between distinct visual or thematic segments.

Provide only the classification string (e.g., "pause").

Text Before Silence: "{context_before}"
Text After Silence: "{context_after}"
"""
    response = model.generate_content(prompt)
    classification = response.text.strip().lower()
    if classification not in ["pause", "dead air", "scene change"]:
        return "unknown"
    return classification