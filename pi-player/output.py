import os
import json
from pyartnet import ArtNetNode, SacnNode
import asyncio

class Outputer:
    def output(self, values):
        pass

class PrintOutputer(Outputer):
    def output(self, values):
        print(values)

class NetworkOutputer(Outputer):

    node: ArtNetNode
    universes = {}
    channels = {}

    def __init__(self, type, ip) -> None:
        super().__init__()
        if type == 'artnet':
            self.node = ArtNetNode(ip, 6454)
        elif type == 'sacn' or type == 'e131':
            self.node = SacnNode(ip, 5568)

    def output(self, values):
        for value in values:
            [u, c, v] = value

            # Make sure universe & channel exist
            if u not in self.universes:
                universe = self.node.add_universe(u)
                self.universes[u] = universe
            chan_key = u * 1000 + c

            if chan_key not in self.channels:
                channel = self.universes[u].add_channel(c, 1)
                self.channels[c] = channel

            self.channels[c].set_values([v])
        

outputer: Outputer = PrintOutputer()


def configure_output(config_file):
    global outputer

    if not os.path.exists(config_file):
        print(f'No output config file "{config_file}". Using print output')
        return
    with open(config_file, 'r') as file:
        data = json.load(file)
        if 'type' not in data:
            print('Config missing "type". Defaulting to print output')
            return
    
        if data['type'] == 'print':
            print('Using print output')
            return
        elif data['type'] == 'artnet':
            if 'ip' not in data:
                print('Config missing "ip" for type = "artnet". Defaulting to print output')
                return
            
            print('Using ArtNet output')
            outputer = NetworkOutputer('artnet', data['ip'])
        elif data['type'] == 'sacn':
            if 'ip' not in data:
                print('Config missing "ip" for type = "sacn". Defaulting to print output')
                return
            
            print('Using sACN output')
            outputer = NetworkOutputer('sacn', data['ip'])


configure_output('output.json')
