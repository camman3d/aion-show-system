import json
import os
from show import Show
import dmx
import time
from window import start_qt_app


config = {}

def read_config():
    global config
    with open('config.json', 'r') as file:
        config = json.load(file)


def build_shows():
    grouped_files = {}
    for filename in os.listdir('shows'):
        name, _ = os.path.splitext(filename)
        full_file = os.path.join('shows/', filename)

        if name in grouped_files:
            grouped_files[name].append(full_file)
        else:
            grouped_files[name] = [full_file]

    shows = []
    for name, files in grouped_files.items():
        show = Show(name, files)
        show.listen(config['mqtt']['host'])
        shows.append(show)


    return shows

read_config()
dmx.configure_dmx(config['dmx']['host'])
shows = build_shows()
start_qt_app()