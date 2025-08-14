import google.generativeai as genai
import srt
from datetime import timedelta
import os
import subprocess
import logging
import json

def transcribe_video(video_path):
    temp_audio_path = "temp_audio.mp3"
    try:
        # 1. Extract audio from video
        command = [
            "ffmpeg",
            "-i", video_path,
            "-q:a", "0",
            "-map", "a",
            temp_audio_path
        ]
        subprocess.run(command, check=True, capture_output=True, text=True)

        # 2. Upload audio to Gemini
        audio_file = genai.upload_file(path=temp_audio_path)

        # 3. Transcribe with Gemini 2.5 Pro
        model = genai.GenerativeModel('gemini-2.5-pro')
        prompt = """Analyze this audio file and provide a word-level transcription.

**CRITICAL INSTRUCTIONS:**
1.  **Diarize Speakers:** Identify and label each speaker (e.g., `SPEAKER_00`, `SPEAKER_01`).
2.  **Provide Word Timestamps:** For every single word, provide a precise start and end time.
3.  **Return JSON Output:** Your final output must be a single, valid JSON object. The object should contain one key, "words", which is a list of all the words you found. Each item in the list must have the following structure:
    - `word`: The transcribed word.
    - `start`: The start time in seconds (float).
    - `end`: The end time in seconds (float).
    - `speaker`: The identified speaker label (string).
"""
        response = model.generate_content([prompt, audio_file], request_options={"timeout": 1200})
        response_text = response.text.strip()
        if "```json" in response_text:
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            json_str = response_text[json_start:json_end]
        else:
            json_str = response_text

        transcription_data = json.loads(json_str)

        # 4. Format the response into SRT
        subs = []
        for i, word_data in enumerate(transcription_data.get("words", [])):
            start_time = timedelta(seconds=word_data['start'])
            end_time = timedelta(seconds=word_data['end'])
            content = f"[{word_data['speaker']}] {word_data['word']}"
            subs.append(srt.Subtitle(index=i + 1, start=start_time, end=end_time, content=content))
        
        srt_content = srt.compose(subs)
        return srt_content

    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logging.error(f"Error during audio extraction: {e}")
        return None
    except Exception as e:
        logging.error(f"An error occurred during transcription: {e}")
        return None
    finally:
        # 5. Clean up temporary audio file
        if os.path.exists(temp_audio_path):
            os.remove(temp_audio_path)