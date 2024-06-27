import os
import json
import pygame
from threading import Thread
import time
from output import outputer
from subprocess import Popen

pygame.mixer.init()


def load_shows(dir_name):
    files = {}
    for f in os.listdir(dir_name):
        name = os.path.splitext(f)[0]
        if name not in files:
            files[name] = []
        files[name].append(os.path.join(dir_name, f))
    
    shows = {}
    for name in files:
        shows[name] = Show(name, files[name])
    return shows

class Show:

    name: str
    audio_file = ''
    video_file = ''
    data = []

    def __init__(self, name, files) -> None:
        self.name = name
        for filename in files:

            if filename.endswith('.json'):
                with open(filename, 'r') as file:
                    self.data = json.load(file)
            
            elif filename.endswith('.mp3'):
                self.audio_file = filename
            
            elif filename.endswith('.mp4'):
                self.video_file = filename

    def play_audio(self):
        pygame.mixer.music.stop()
        pygame.mixer.music.load(self.audio_file)
        pygame.mixer.music.play()

    def play_video(self):
        if os.name == 'nt':
            # Windows
            Popen(['C:\\Program Files\\VideoLAN\\VLC\\vlc.exe', '--fullscreen', self.video_file])
        elif os.name == 'posix':
            # Linux
            os.system('killall omxplayer.bin')
            Popen(['omxplayer', '-b', self.video_file])
        else:
            print(f'Cannot play video on unsupported os type: {os.name}')

    def play_data(self):
        last_time = 0
        for row in self.data:
            time_to_wait = row[0] - last_time
            if time_to_wait > 0:
                time.sleep(time_to_wait)
            
            array = row[1:]
            groups = [array[i:i + 2] for i in range(0, len(array), 2)]
            outputer.output(groups)

    def play(self):
        if len(self.audio_file) > 0:
            self.play_audio()
        if len(self.video_file) > 0:
            self.play_video()
        if len(self.data) > 0:
            self.play_data()
        
        # Wait for audio to finish
        if len(self.audio_file) > 0:
            while pygame.mixer.music.get_busy():
                time.sleep(0.1)
    
    def play_threaded(self):
        thread = Thread(target=self.play, args=[])
        thread.start()
        return thread
