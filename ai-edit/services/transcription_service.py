import google.generativeai as genai
import srt
from datetime import timedelta
import os
import subprocess
import logging
import json
import re

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
3.  **Return JSON Output ONLY:** Your entire output must be ONLY the JSON object, with no additional text, explanations, or markdown formatting like ```json. The response should be immediately parsable as JSON. The object must contain one key, "words", which is a list of all the words you found. Each item in the list must have the following structure:
    - `word`: The transcribed word.
    - `start`: The start time in seconds (float).
    - `end`: The end time in seconds (float).
    - `speaker`: The identified speaker label (string).

**EXAMPLE OF THE ONLY VALID OUTPUT FORMAT:**
{
  "words": [
    {
      "word": "Hello",
      "start": 0.5,
      "end": 1.0,
      "speaker": "SPEAKER_00"
    },
    {
      "word": "world",
      "start": 1.1,
      "end": 1.5,
      "speaker": "SPEAKER_00"
    }
  ]
}
"""
        response = model.generate_content([prompt, audio_file], request_options={"timeout": 1200})
        
        if not response.candidates or not response.candidates[0].content.parts:
            logging.warning("The Gemini API did not return any content for transcription. This might indicate a silent audio or an issue with the input.")
            return None

        try:
            response_text = response.text.strip()
        except ValueError:
            logging.warning("The response from the transcription service was empty after stripping. This may be because the video is silent.")
            return None

        # Extract JSON from the response text
        json_match = re.search(r'```json\n(.*?)\n```', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Fallback for cases where the model doesn't use markdown code blocks
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            if json_start != -1 and json_end != -1:
                json_str = response_text[json_start:json_end]
            else:
                logging.error(f"Could not find JSON in the response: {response_text}")
                return None

        try:
            transcription_data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logging.error(f"Error decoding JSON from transcription response: {e}")
            logging.error(f"Invalid JSON string: {json_str}")
            # Attempt to fix the JSON by adding missing commas
            fixed_json_str = re.sub(r'}\s*{', '},{', json_str)
            try:
                transcription_data = json.loads(fixed_json_str)
                logging.info("Successfully repaired JSON by adding missing commas.")
            except json.JSONDecodeError:
                logging.error("Failed to repair JSON by adding commas. Trying to repair with LLM.")
                # Attempt to repair the JSON
                repair_prompt = f"The following JSON is invalid. Please fix it and return only the corrected JSON.\n\n{json_str}"
                repair_response = model.generate_content(repair_prompt)
                repaired_json_str = repair_response.text.strip()
                try:
                    transcription_data = json.loads(repaired_json_str)
                except json.JSONDecodeError as e2:
                    logging.error(f"Failed to repair JSON: {e2}")
                    logging.error(f"Repaired JSON string: {repaired_json_str}")
                    return None

        # 4. Format the response into SRT
        subs = []
        unique_speakers = set(word_data['speaker'] for word_data in transcription_data.get("words", []))
        include_speakers = len(unique_speakers) > 1

        for i, word_data in enumerate(transcription_data.get("words", [])):
            start_time = timedelta(seconds=word_data['start'])
            end_time = timedelta(seconds=word_data['end'])
            if include_speakers:
                content = f"[{word_data['speaker']}] {word_data['word']}"
            else:
                content = word_data['word']
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
