import subprocess
import srt
import re
import json
from datetime import timedelta
import os
import logging
import time

def get_video_metadata(video_path):
    command = [
        "ffprobe",
        "-v", "error",
        "-show_streams",
        "-of", "json",
        video_path
    ]
    process = subprocess.run(command, capture_output=True, text=True)
    if process.returncode != 0:
        raise Exception(f"ffprobe error: {process.stderr}")
    
    metadata = json.loads(process.stdout)
    
    video_stream = None
    audio_stream = None
    for stream in metadata["streams"]:
        if stream['codec_type'] == 'video':
            video_stream = stream
        elif stream['codec_type'] == 'audio':
            audio_stream = stream

    if not video_stream:
        raise Exception("No video stream found")

    width = video_stream.get("width")
    height = video_stream.get("height")
    display_aspect_ratio = video_stream.get("display_aspect_ratio")
    duration = float(video_stream.get("duration", 0))
    
    if 'r_frame_rate' in video_stream and video_stream['r_frame_rate'] != '0/0':
        num, den = map(int, video_stream['r_frame_rate'].split('/'))
        frame_rate = num / den
    else:
        frame_rate = 30 # default

    aspect_ratio_str = "unknown"
    if display_aspect_ratio:
        parts = display_aspect_ratio.split(':')
        if len(parts) == 2:
            try:
                ar_width = int(parts[0])
                ar_height = int(parts[1])
                aspect_ratio_str = f"{ar_width}:{ar_height}"
            except ValueError:
                pass

    if aspect_ratio_str == "unknown" and width and height:
        from fractions import Fraction
        aspect_ratio_fraction = Fraction(width, height).limit_denominator()
        aspect_ratio_str = f"{aspect_ratio_fraction.numerator}:{aspect_ratio_fraction.denominator}"

    result = {
        "width": width, 
        "height": height, 
        "aspect_ratio": aspect_ratio_str, 
        "duration": duration,
        "frame_rate": frame_rate
    }

    if audio_stream:
        result["audio"] = {
            "sample_rate": int(audio_stream.get("sample_rate", 44100)),
            "channels": int(audio_stream.get("channels", 1))
        }
    
    return result

def timedelta_string_to_seconds(td_str):
    """Converts a time string in formats like HH:MM:SS.ms or seconds to seconds."""
    parts = str(td_str).replace(',', '.').split(':')
    if len(parts) == 3:
        h, m, s = map(float, parts)
        return h * 3600 + m * 60 + s
    elif len(parts) == 2:
        m, s = map(float, parts)
        return m * 60 + s
    elif len(parts) == 1:
        return float(parts[0])
    else:
        raise ValueError(f"Invalid time format: {td_str}")



def apply_noise_reduction(input_path, output_path, task_id, task_status):
    task_status[task_id].update({"status": "NOISE_REDUCTION", "progress": 30, "message": f"Applying noise reduction to {input_path}"})
    logging.info(f"[{task_id}] Applying noise reduction to {input_path}, output to {output_path}")
    command = [
        "ffmpeg",
        "-i", input_path,
        "-af", "afftdn",
        "-c:v", "copy",
        output_path
    ]
    try:
        logging.info(f"Executing FFmpeg noise reduction command: {' '.join(command)}")
        process = subprocess.run(command, check=True, capture_output=True, text=True)
        logging.info(f"FFmpeg noise reduction stdout: {process.stdout}")
        logging.info(f"FFmpeg noise reduction stderr: {process.stderr}")
        task_status[task_id].update({"status": "NOISE_REDUCTION_COMPLETE", "progress": 40, "message": "Noise reduction applied successfully."})
        logging.info(f"[{task_id}] Noise reduction applied successfully.")
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"Error applying noise reduction: {e.stderr}")
        task_status[task_id].update({"status": "NOISE_REDUCTION_FAILED", "progress": 40, "message": f"Noise reduction failed: {e.stderr}"})
        return False

def cut_video_segments(input_path, segments_to_keep, output_path):
    if not segments_to_keep:
        logging.info("No segments to keep, copying original video.")
        try:
            subprocess.run(["ffmpeg", "-i", input_path, "-c", "copy", "-y", output_path], check=True, capture_output=True, text=True)
            return True
        except subprocess.CalledProcessError as e:
            logging.error(f"Error copying video: {e.stderr}")
            return False

    filter_complex_parts = []
    video_outputs = []
    audio_outputs = []

    for i, segment in enumerate(segments_to_keep):
        start = segment['start']
        end = segment['end']
        video_outputs.append(f"[v{i}]")
        audio_outputs.append(f"[a{i}]")
        filter_complex_parts.append(f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}];")
        filter_complex_parts.append(f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}];")

    filter_complex_parts.append("".join(video_outputs) + f"concat=n={len(segments_to_keep)}:v=1:a=0[outv];")
    filter_complex_parts.append("".join(audio_outputs) + f"concat=n={len(segments_to_keep)}:v=0:a=1[outa]")

    filter_complex = "".join(filter_complex_parts)

    command = [
        "ffmpeg",
        "-i", input_path,
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "[outa]",
        "-y",
        output_path
    ]

    try:
        logging.info(f"Executing FFmpeg command: {' '.join(command)}")
        process = subprocess.run(command, check=True, capture_output=True, text=True)
        logging.info(f"FFmpeg stdout: {process.stdout}")
        logging.info(f"FFmpeg stderr: {process.stderr}")
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"Error cutting video segments: {e.stderr}")
        return False

def _format_timedelta_for_ass(td):
    total_seconds = td.total_seconds()
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)
    centiseconds = int((total_seconds * 100) % 100)
    return f"{hours}:{minutes:02}:{seconds:02}.{centiseconds:02}"

def burn_srt_to_video(video_path, srt_path, output_path, ass_style=None):
    # Convert SRT to ASS for advanced styling
    ass_path = os.path.splitext(srt_path)[0] + ".ass"
    with open(srt_path, 'r', encoding='utf-8') as f_srt:
        subs = list(srt.parse(f_srt.read()))

    with open(ass_path, 'w', encoding='utf-8') as f_ass:
        f_ass.write("[Script Info]\n")
        f_ass.write("Title: Generated by Storyboard AI\n")
        f_ass.write("ScriptType: v4.00+\n")
        f_ass.write("WrapStyle: 0\n")
        f_ass.write("PlayResX: 1920\n")
        f_ass.write("PlayResY: 1080\n")
        f_ass.write("ScaledBorderAndShadow: yes\n\n")
        f_ass.write("[V4+ Styles]\n")
        f_ass.write("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n")
        
        if ass_style:
            style_name = "Styled"
            fontname = ass_style.get("Fontname", "Arial")
            fontsize = ass_style.get("Fontsize", "72")
            primary_colour = ass_style.get("PrimaryColour", "&H00FFFFFF")
            outline = ass_style.get("Outline", "3")
            shadow = ass_style.get("Shadow", "2")
            
            alignment = "2" # Bottom Center
            if ass_style.get("position") == "Top":
                alignment = "8"
            elif ass_style.get("position") == "Middle":
                alignment = "5"

            f_ass.write(f"Style: {style_name},{fontname},{fontsize},{primary_colour},&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,{outline},{shadow},{alignment},30,30,30,1\n")
        else:
            style_name = "Default"
            f_ass.write("Style: Default,Arial,72,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,3,2,2,30,30,30,1\n")

        f_ass.write("\n[Events]\n")
        f_ass.write("Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
        for sub in subs:
            start_time = _format_timedelta_for_ass(sub.start)
            end_time = _format_timedelta_for_ass(sub.end)
            f_ass.write(f"Dialogue: 0,{start_time},{end_time},{style_name},,0,0,0,,{sub.content}\n")

    escaped_ass_path = ass_path.replace('\\', '/').replace(':', '\\:')

    command = [
        "ffmpeg",
        "-i", video_path,
        "-vf", f"ass={escaped_ass_path}",
        "-c:a", "copy",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",
        "-y",
        output_path
    ]


    try:
        logging.info(f"Executing FFmpeg command: {' '.join(command)}")
        process = subprocess.run(command, check=True, capture_output=True, text=True)
        logging.info(f"FFmpeg stdout: {process.stdout}")
        logging.info(f"FFmpeg stderr: {process.stderr}")
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"Error burning subtitles to video: {e.stderr}")
        return False


def extract_clip(input_path, start_time, end_time, output_path):
    """
    Extracts a clip from a video file.
    """
    command = [
        "ffmpeg",
        "-i", input_path,
        "-ss", str(start_time),
        "-to", str(end_time),
        "-c", "copy",
        output_path
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"Error extracting clip: {e.stderr}")
        return False
