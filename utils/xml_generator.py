import xml.etree.ElementTree as ET
from xml.dom import minidom
import os

def generate_premiere_xml(output_path, video_metadata, segments_to_keep, video_filename):
    frame_rate = video_metadata.get("frame_rate", 30)
    width = video_metadata.get("width", 1920)
    height = video_metadata.get("height", 1080)
    audio_sample_rate = video_metadata.get("audio", {}).get("sample_rate", 44100)
    audio_channels = video_metadata.get("audio", {}).get("channels", 1)
    video_duration_frames = int(video_metadata.get("duration", 0) * frame_rate)

    xmeml = ET.Element("xmeml", version="4")
    sequence = ET.SubElement(xmeml, "sequence", id="sequence-1")
    ET.SubElement(sequence, "name").text = os.path.splitext(video_filename)[0]
    
    rate = ET.SubElement(sequence, "rate")
    ET.SubElement(rate, "timebase").text = str(int(frame_rate))
    ET.SubElement(rate, "ntsc").text = "TRUE"

    media = ET.SubElement(sequence, "media")
    video = ET.SubElement(media, "video")
    video_format = ET.SubElement(video, "format")
    video_sample_char = ET.SubElement(video_format, "samplecharacteristics")
    ET.SubElement(video_sample_char, "width").text = str(width)
    ET.SubElement(video_sample_char, "height").text = str(height)
    ET.SubElement(video_sample_char, "anamorphic").text = "FALSE"
    ET.SubElement(video_sample_char, "pixelaspectratio").text = "square"
    ET.SubElement(video_sample_char, "fielddominance").text = "none"
    ET.SubElement(video_sample_char, "colordepth").text = "24"
    v_rate = ET.SubElement(video_sample_char, "rate")
    ET.SubElement(v_rate, "timebase").text = str(int(frame_rate))
    ET.SubElement(v_rate, "ntsc").text = "TRUE"

    video_track = ET.SubElement(video, "track")
    
    audio = ET.SubElement(media, "audio")
    ET.SubElement(audio, "numOutputChannels").text = "2"
    audio_format = ET.SubElement(audio, "format")
    audio_sample_char = ET.SubElement(audio_format, "samplecharacteristics")
    ET.SubElement(audio_sample_char, "depth").text = "16"
    ET.SubElement(audio_sample_char, "samplerate").text = str(audio_sample_rate)
    audio_track = ET.SubElement(audio, "track")

    timeline_cursor = 0
    clip_counter = 1

    file_id_map = {}
    file_counter = 1

    for segment in segments_to_keep:
        in_point = int(segment['start'] * frame_rate)
        out_point = int(segment['end'] * frame_rate)
        clip_duration = out_point - in_point

        # --- Video Clip --- 
        video_clipitem = ET.SubElement(video_track, "clipitem", id=f"clipitem-{clip_counter}")
        ET.SubElement(video_clipitem, "name").text = video_filename
        ET.SubElement(video_clipitem, "enabled").text = "TRUE"
        ET.SubElement(video_clipitem, "duration").text = str(clip_duration)
        ET.SubElement(video_clipitem, "start").text = str(timeline_cursor)
        ET.SubElement(video_clipitem, "end").text = str(timeline_cursor + clip_duration)
        ET.SubElement(video_clipitem, "in").text = str(in_point)
        ET.SubElement(video_clipitem, "out").text = str(out_point)

        if video_filename not in file_id_map:
            file_id_map[video_filename] = f"file-{file_counter}"
            file_counter += 1
        
        file_id = file_id_map[video_filename]
        file_element = ET.SubElement(video_clipitem, "file", id=file_id)

        if file_id == f"file-{file_counter-1}": # Only add full file info for the first time
            ET.SubElement(file_element, "name").text = video_filename
            ET.SubElement(file_element, "pathurl").text = video_filename
            ET.SubElement(file_element, "duration").text = str(video_duration_frames)
            f_rate = ET.SubElement(file_element, "rate")
            ET.SubElement(f_rate, "timebase").text = str(int(frame_rate))
            ET.SubElement(f_rate, "ntsc").text = "TRUE"
            f_media = ET.SubElement(file_element, "media")
            f_video = ET.SubElement(f_media, "video")
            f_video_sample = ET.SubElement(f_video, "samplecharacteristics")
            ET.SubElement(f_video_sample, "width").text = str(width)
            ET.SubElement(f_video_sample, "height").text = str(height)
            f_audio = ET.SubElement(f_media, "audio")
            f_audio_sample = ET.SubElement(f_audio, "samplecharacteristics")
            ET.SubElement(f_audio_sample, "depth").text = "16"
            ET.SubElement(f_audio_sample, "samplerate").text = str(audio_sample_rate)
            ET.SubElement(f_audio, "channelcount").text = str(audio_channels)

        # --- Audio Clip --- 
        audio_clipitem = ET.SubElement(audio_track, "clipitem", id=f"clipitem-{clip_counter+1}")
        ET.SubElement(audio_clipitem, "name").text = video_filename
        ET.SubElement(audio_clipitem, "enabled").text = "TRUE"
        ET.SubElement(audio_clipitem, "duration").text = str(clip_duration)
        ET.SubElement(audio_clipitem, "start").text = str(timeline_cursor)
        ET.SubElement(audio_clipitem, "end").text = str(timeline_cursor + clip_duration)
        ET.SubElement(audio_clipitem, "in").text = str(in_point)
        ET.SubElement(audio_clipitem, "out").text = str(out_point)
        ET.SubElement(audio_clipitem, "file", id=file_id)

        # --- Linking --- 
        link1 = ET.SubElement(video_clipitem, "link")
        ET.SubElement(link1, "linkclipref").text = f"clipitem-{clip_counter}"
        ET.SubElement(link1, "mediatype").text = "video"
        ET.SubElement(link1, "trackindex").text = "1"
        ET.SubElement(link1, "clipindex").text = str(len(video_track))

        link2 = ET.SubElement(video_clipitem, "link")
        ET.SubElement(link2, "linkclipref").text = f"clipitem-{clip_counter+1}"
        ET.SubElement(link2, "mediatype").text = "audio"
        ET.SubElement(link2, "trackindex").text = "1"
        ET.SubElement(link2, "clipindex").text = str(len(audio_track))
        ET.SubElement(link2, "groupindex").text = "1"

        link3 = ET.SubElement(audio_clipitem, "link")
        ET.SubElement(link3, "linkclipref").text = f"clipitem-{clip_counter}"
        ET.SubElement(link3, "mediatype").text = "video"
        ET.SubElement(link3, "trackindex").text = "1"
        ET.SubElement(link3, "clipindex").text = str(len(video_track))

        link4 = ET.SubElement(audio_clipitem, "link")
        ET.SubElement(link4, "linkclipref").text = f"clipitem-{clip_counter+1}"
        ET.SubElement(link4, "mediatype").text = "audio"
        ET.SubElement(link4, "trackindex").text = "1"
        ET.SubElement(link4, "clipindex").text = str(len(audio_track))
        ET.SubElement(link4, "groupindex").text = "1"

        timeline_cursor += clip_duration
        clip_counter += 2

    ET.SubElement(sequence, "duration").text = str(timeline_cursor)

    xml_str = ET.tostring(xmeml, encoding='utf-8', method='xml')
    reparsed = minidom.parseString(xml_str)
    pretty_xml_str = reparsed.toprettyxml(indent="  ", encoding="utf-8").decode('utf-8')

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(pretty_xml_str)
