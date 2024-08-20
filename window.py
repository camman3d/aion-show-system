import sys
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget
from PyQt5.QtGui import QCursor

window = None


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Aion Show System")
        self.showFullScreen()
        self.setStyleSheet("background-color: black;")
        self.setCursor(QCursor(Qt.BlankCursor))

        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        self.videoWidget = QVideoWidget()
        self.layout.addWidget(self.videoWidget)

        self.mediaPlayer = QMediaPlayer(None, QMediaPlayer.VideoSurface)
        self.mediaPlayer.setVideoOutput(self.videoWidget)
        

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        elif event.key() == Qt.Key.Key_Q:
            self.stopMedia()
    
    def playMedia(self, path):
        content = QMediaContent(QUrl(path))
        self.mediaPlayer.setMedia(content)
        self.mediaPlayer.play()

    def stopMedia(self):
        self.mediaPlayer.stop()


def start_qt_app():
    global window
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


def play_qt_media(path):
    if path is None:
        window.stopMedia()
    else:
        window.playMedia(path)
