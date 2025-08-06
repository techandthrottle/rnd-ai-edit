import subprocess
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
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,display_aspect_ratio,duration",
        "-of", "json",
        video_path
    ]
    process = subprocess.run(command, capture_output=True, text=True)
    if process.returncode != 0:
        raise Exception(f"ffprobe error: {process.stderr}")
    
    metadata = json.loads(process.stdout)
    stream = metadata["streams"][0]
    
    width = stream.get("width")
    height = stream.get("height")
    display_aspect_ratio = stream.get("display_aspect_ratio")
    duration = float(stream.get("duration", 0)) # Get duration

    if display_aspect_ratio:
        parts = display_aspect_ratio.split(':')
        if len(parts) == 2:
            try:
                ar_width = int(parts[0])
                ar_height = int(parts[1])
                return {"width": width, "height": height, "aspect_ratio": f"{ar_width}:{ar_height}", "duration": duration}
            except ValueError:
                pass

    if width and height:
        from fractions import Fraction
        aspect_ratio_fraction = Fraction(width, height).limit_denominator()
        return {"width": width, "height": height, "aspect_ratio": f"{aspect_ratio_fraction.numerator}:{aspect_ratio_fraction.denominator}", "duration": duration}

    return {"width": width, "height": height, "aspect_ratio": "unknown", "duration": duration}

def timedelta_string_to_seconds(td_str):
    parts = td_str.split(':')
    h = float(parts[0])
    m = float(parts[1])
    s = float(parts[2])
    return h * 3600 + m * 60 + s

def detect_silence(video_path):
    command = [
        "ffmpeg",
        "-i", video_path,
        "-af", "silencedetect=n=-50dB:d=1",
        "-f", "null",
        "-"
    ]
    process = subprocess.run(command, capture_output=True, text=True)
    output = process.stderr

    silence_intervals = []
    starts = re.findall(r"silence_start: (\d+\.?\d*)", output)
    ends = re.findall(r"silence_end: (\d+\.?\d*)", output)

    for i in range(len(starts)):
        start = float(starts[i])
        end = float(ends[i])
        silence_intervals.append({"start": str(timedelta(seconds=start)), "end": str(timedelta(seconds=end))})
    return silence_intervals

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
        process = subprocess.run(command, check=True, capture_output=True, text=True, timeout=300)
        logging.info(f"FFmpeg noise reduction stdout: {process.stdout}")
        logging.info(f"FFmpeg noise reduction stderr: {process.stderr}")
        task_status[task_id].update({"status": "NOISE_REDUCTION_COMPLETE", "progress": 40, "message": "Noise reduction applied successfully."})
        logging.info(f"[{task_id}] Noise reduction applied successfully.")
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"Error applying noise reduction: {e.stderr}")
        task_status[task_id].update({"status": "NOISE_REDUCTION_FAILED", "progress": 40, "message": f"Noise reduction failed: {e.stderr}"})
        return False
    except subprocess.TimeoutExpired:
        logging.error("Noise reduction process timed out after 300 seconds.")
        task_status[task_id].update({"status": "NOISE_REDUCTION_FAILED", "progress": 40, "message": "Noise reduction process timed out."})
        return False

def cut_video_segments(input_path, segments_to_keep, output_path, crossfade_duration=0.05):
    if not segments_to_keep:
        command = [
            "ffmpeg",
            "-i", input_path,
            "-c", "copy",
            output_path
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
            return True
        except subprocess.CalledProcessError as e:
            print(f"Error copying video: {e.stderr}")
            return False

    # Generate a complex filtergraph for trimming and crossfading
    filter_complex = []
    video_streams = []
    audio_streams = []
    last_video_stream = ""
    last_audio_stream = ""

    # Trim each segment
    for i, segment in enumerate(segments_to_keep):
        start = segment['start']
        end = segment['end']
        video_streams.append(f"[v{i}]")
        audio_streams.append(f"[a{i}]")
        filter_complex.append(f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}];")
        filter_complex.append(f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}];")

    # Chain the segments together with crossfades
    if len(segments_to_keep) > 1:
        last_video_stream = "[v_out_0]"
        last_audio_stream = "[a_out_0]"
        filter_complex.append(f"[v0][v1]xfade=transition=fade:duration={crossfade_duration}:offset={segments_to_keep[0]['end'] - segments_to_keep[0]['start'] - crossfade_duration}[v_out_0];")
        filter_complex.append(f"[a0][a1]acrossfade=d={crossfade_duration}[a_out_0];")

        for i in range(1, len(segments_to_keep) - 1):
            offset = segments_to_keep[i]['end'] - segments_to_keep[i]['start'] - crossfade_duration
            filter_complex.append(f"[v_out_{i-1}][v{i+1}]xfade=transition=fade:duration={crossfade_duration}:offset={offset}[v_out_{i}];")
            filter_complex.append(f"[a_out_{i-1}][a{i+1}]acrossfade=d={crossfade_duration}[a_out_{i}];")
            last_video_stream = f"[v_out_{i}]"
            last_audio_stream = f"[a_out_{i}]"

    else: # Only one segment
        last_video_stream = "[v0]"
        last_audio_stream = "[a0]"

    command = [
        "ffmpeg",
        "-i", input_path,
        "-filter_complex", "".join(filter_complex),
        "-map", last_video_stream,
        "-map", last_audio_stream,
        "-y",
        output_path
    ]

    try:
        logging.info(f"Executing FFmpeg command: {' '.join(command)}")
        process = subprocess.run(command, check=True, capture_output=True, text=True, timeout=600)
        logging.info(f"FFmpeg stdout: {process.stdout}")
        logging.info(f"FFmpeg stderr: {process.stderr}")
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"Error cutting video segments with crossfade: {e.stderr}")
        return False
    except subprocess.TimeoutExpired:
        logging.error("Video cutting process with crossfade timed out after 600 seconds.")
        return False

def burn_srt_to_video(video_path, srt_path, output_path, ass_style=None):
    ass_path = os.path.splitext(srt_path)[0] + ".ass"
    try:
        position = ass_style.get("position", "Bottom").lower()
        alignment = {"top": 8, "middle": 5, "bottom": 2}.get(position, 2)

        style_line = "Style: Default,"
        style_line += ass_style.get("Fontname", "Arial") + ","
        style_line += str(ass_style.get("Fontsize", "72")) + ","
        style_line += ass_style.get("PrimaryColour", "&H00FFFFFF") + ","
        style_line += ass_style.get("SecondaryColour", "&H000000FF") + ","
        style_line += ass_style.get("OutlineColour", "&H00000000") + ","
        style_line += ass_style.get("BackColour", "&H80000000") + ","
        style_line += str(ass_style.get("Bold", 0)) + ","
        style_line += str(ass_style.get("Italic", 0)) + ","
        style_line += str(ass_style.get("Underline", 0)) + ","
        style_line += str(ass_style.get("StrikeOut", 0)) + ","
        style_line += str(ass_style.get("ScaleX", 100)) + ","
        style_line += str(ass_style.get("ScaleY", 100)) + ","
        style_line += str(ass_style.get("Spacing", 0)) + ","
        style_line += str(ass_style.get("Angle", 0)) + ","
        style_line += str(ass_style.get("BorderStyle", 1)) + ","
        style_line += str(ass_style.get("Outline", 3)) + ","
        style_line += str(ass_style.get("Shadow", 2)) + ","
        style_line += str(alignment) + ","
        style_line += str(ass_style.get("MarginL", 30)) + ","
        style_line += str(ass_style.get("MarginR", 30)) + ","
        style_line += str(ass_style.get("MarginV", 30)) + ","
        style_line += str(ass_style.get("Encoding", 1))

        ass_content = f'''[Script Info]
Title: Generated by Storyboard AI
ScriptType: v4.00+
WrapStyle: 0
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{style_line}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
        with open(srt_path, 'r', encoding='utf-8') as srt_file:
            srt_content = srt_file.read()

        srt_blocks = re.split(r'\n\s*\n', srt_content.strip())
        for block in srt_blocks:
            lines = block.strip().split('\n')
            if len(lines) >= 2 and '-->' in lines[1]:
                start_time_str, end_time_str = [t.strip() for t in lines[1].split('-->')]
                start_time_ass = start_time_str.replace(',', '.')[:-1]
                end_time_ass = end_time_str.replace(',', '.')[:-1]
                text = " ".join(lines[2:])
                ass_content += f"Dialogue: 0,{start_time_ass},{end_time_ass},Default,,0,0,0,,{text}\n"

        with open(ass_path, 'w', encoding='utf-8') as ass_file:
            ass_file.write(ass_content)

        safe_ass_path = ass_path.replace('\\', '/')
        command = [
            "ffmpeg",
            "-i", video_path,
            "-vf", f"ass={safe_ass_path}",
            "-c:a", "copy",
            output_path
        ]

    except Exception as e:
        logging.error(f"Error generating ASS file: {e}")
        return False

    try:
        logging.info(f"Executing FFmpeg command: {' '.join(command)}")
        process = subprocess.run(command, check=True, capture_output=True, text=True)
        logging.info(f"FFmpeg stdout: {process.stdout}")
        logging.info(f"FFmpeg stderr: {process.stderr}")
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"Error burning subtitles to video: {e.stderr}")
        return False
    finally:
        if os.path.exists(ass_path):
            os.remove(ass_path)
