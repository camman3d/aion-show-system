
## Setup

Place any media files in the `shows` directory.

## Installing


### Windows

When running on Windows, it will use the windows Media Foundation backend. This is by default and so you can install normally with pip:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Raspberry Pi

With Raspberry Pi we need to use the gstreamer backend. First install and set up gstreamer:

```bash
sudo apt update
sudo apt install gstreamer1.0-tools gstreamer1.0-qt6
```

Then install python deps via apt. This is needed to connect Qt to the gstreamer backend:

```bash
sudo apt install python3-pyqt6 \
    python3-pyqt6.qtmultimedia \
    python3-paho-mqtt \
    python3-sacn
```

qt6-multimedia-dev \
libgstreamer-plugins-base1.0-dev \
libgstreamer-plugins-bad1.0-dev \
gstreamer1.0-plugins-ugly \
libx264-dev \
    libjpeg-dev \
libgstreamer1.0-dev \
    gstreamer1.0-libav

## Running

```
python main.py
```