import sys
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtGui import QCursor

window = None


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Aion Show System")
        self.showFullScreen()
        self.setStyleSheet("background-color: black;")
        self.setCursor(QCursor(Qt.CursorShape.BlankCursor))

        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        self.videoWidget = QVideoWidget()
        self.layout.addWidget(self.videoWidget)

        self.mediaPlayer = QMediaPlayer()
        self.audioOutput = QAudioOutput()
        self.audioOutput.setVolume(100)
        self.mediaPlayer.setAudioOutput(self.audioOutput)
        self.mediaPlayer.setVideoOutput(self.videoWidget)
        

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        elif event.key() == Qt.Key.Key_Q:
            self.stopMedia()
    
    def playMedia(self, path):
        content = QUrl.fromLocalFile(path)
        self.mediaPlayer.setSource(content)
        self.mediaPlayer.play()

    def stopMedia(self):
        self.mediaPlayer.stop()


def start_qt_app():
    global window
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


def play_qt_media(path):
    if path is None:
        window.stopMedia()
    else:
        window.playMedia(path)
