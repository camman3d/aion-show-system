import sys
import time

if len(sys.argv) != 2:
    print('Usage: python main.py {broker_address}')
    exit(1)
broker_address = sys.argv[1]

from show import load_shows
shows = load_shows('show')

import paho.mqtt.client as mqtt
client = mqtt.Client()

def on_connect(client, userdata, flags, rc):
    print("Connected with result code "+str(rc))

    for show in shows:
        client.subscribe('/show/' + show)


def on_message(client, userdata, msg):
    payload = str(msg.payload.decode())
    parts = msg.topic.split('/')
    if parts[1] == 'show':
        show = shows[parts[2]]
        if not show:
            print(f'Unable to find show: {parts[2]}')
        else:
            if payload == 'play':
                show.play_threaded()
            else:
                print('Unsupported show action: ' + payload)
    else:
        print(f"Received message on topic {msg.topic}: {str(msg.payload.decode())}")


client.on_connect = on_connect
client.on_message = on_message

client.connect(broker_address, 1883, 60)
client.loop_start()

try:
    while True:
        # Publish a command every 60 seconds
        # client.publish("/devices/led/1/command", "toggle")
        print('alive')
        time.sleep(60)
except KeyboardInterrupt:
    print("Exiting...")
    client.loop_stop()
    client.disconnect()

# Publish a trigger event
# client.publish("/devices/led/1/command", "on")
