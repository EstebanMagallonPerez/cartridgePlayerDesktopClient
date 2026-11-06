import json
import os
import platform
import threading
import time

if platform.system() == "Darwin":
    from Cocoa import NSApplication
from helpers.stats import Stats
from helpers.music import MusicPlayer
from helpers.reader import NFCReader
from helpers.communicator import ESP32Communicator
from helpers import retroArch
from pyvidplayer2 import Video


ESP32_COM_PORT = "/dev/tty.usbserial-110"
DEFAULT_VIDEO_PATH = "./videos/bbb.mp4"
DEFAULT_ARTWORK = "./data/icon.png"


cwd = os.getcwd()

player = None
reader = None
gameProcess = None
vid = None
comm = None
stats = None

lastState = None
lastReportedNFCState = None

ThreadWatcher = {}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def displayCurrentStats():
    if not stats.current_nfc_tag:
        log("No current NFC tag")
        return

    tag_stats = stats.getTagStats(stats.current_nfc_tag)
    comm.sendListText(stats.build_stats_info(tag_stats))
    stats.current_stats_visible = True


def restoreCurrentView():
    if not stats.current_nfc_tag:
        return

    if stats.current_session_type == "music" and player is not None:
        comm.updateNowPlaying(
            player.folder,
            current_index=player.index
        )

    stats.current_stats_visible = False


def toggleCurrentStats():
    if stats.current_stats_visible:
        restoreCurrentView()
    else:
        displayCurrentStats()


def handleCommunication(message):
    global player, vid

    cmd = message.strip()

    for opcode in cmd:
        try:
            if player is not None:

                if opcode == "0":
                    player.prev()

                elif opcode == "1":
                    player.toggle()

                elif opcode == "2":
                    player.next()

                elif opcode == "4":
                    toggleCurrentStats()

                elif opcode == "8":
                    player.increaseVolume()

                elif opcode == "9":
                    player.decreaseVolume()

            elif vid is not None:

                if opcode == "0":
                    vid.seek(-5)

                elif opcode == "1":
                    if vid.paused:
                        vid.resume()
                    else:
                        vid.pause()

                elif opcode == "2":
                    vid.seek(5)

            elif gameProcess is not None:

                if opcode == "4":
                    toggleCurrentStats()

        except Exception as e:
            log(f"Command error: {e}")


def launchVideo(video_path):
    global vid

    log("Launching video")

    if not os.path.exists(video_path):
        raise FileNotFoundError(video_path)

    vid = Video(video_path)
    vid.preview()

    log("Video finished")


def processStateChange(data):
    global player
    global gameProcess
    global vid
    global lastState
    global ThreadWatcher

    log(f"State change. NFC present={data.nfcFound}")

    if data.nfcFound:

        if lastState is True:
            log("Duplicate insert ignored")
            return

        lastState = True

        tag = (data.currentData or "").strip()

        log(f"Tag detected: {tag}")

        #
        # VIDEO
        #
        if tag.lower().startswith("video|"):

            video_name = tag.split("|", 1)[1].strip()

            stats.beginNFCSession(
                tag,
                "video",
                video_name,
                ["Video Cartridge"]
            )

            comm.setTitle(video_name)

            threading.Thread(
                target=launchVideo,
                args=(DEFAULT_VIDEO_PATH,),
                daemon=True
            ).start()

            return

        #
        # RETRO
        #
        if tag.lower().startswith("retro|"):

            parsed = retroArch.parseRetroTag(tag)

            if parsed:
                console, game = parsed
            else:
                console = ""
                game = None

            stats.beginNFCSession(
                tag,
                "retro",
                game,
                [f"Console: {console}"]
            )

            if game is None:
                game = console

            retro_info = retroArch.getRetroGameInfo(game)

            if retro_info:
                comm.sendArtwork(
                    retro_info["artwork"]
                )

                time.sleep(0.15)

                comm.setTitle(
                    retro_info["title"]
                )

                tag_stats = stats.getTagStats(tag)

                comm.sendListText(
                    stats.build_stats_info(tag_stats)
                )

            log("Launching RetroArch")

            gameProcess = retroArch.launchGame(game)

            return

        #
        # MUSIC
        #
        log("Creating MusicPlayer")

        player = MusicPlayer(tag, comm)

        playlist_meta = {}

        playlist_path = os.path.join(
            player.folder,
            "playlist.json"
        )

        try:
            with open(
                playlist_path,
                "r",
                encoding="utf-8"
            ) as f:
                playlist_meta = json.load(f)

        except Exception:
            pass

        stats.beginNFCSession(
            tag,
            "music",
            player.playlist_title,
            [
                f"Playlist: {player.playlist_title}"
            ],
            metadata=playlist_meta
        )

        comm.initPlaylist(
            player.folder,
            current_index=player.index
        )

        musicThread = threading.Thread(
            target=player.playerLoop,
            daemon=True
        )
        musicThread.start()

        ThreadWatcher["MusicPlayerLoop"+player.playlist_title] = musicThread

        log("Music started")

        return

    #
    # REMOVE CARTRIDGE
    #

    if lastState is False:
        return

    log("Removing cartridge")
    player.alive = False

    lastState = False

    stats.endNFCSession()

    if vid:
        try:
            vid.stop()
        except Exception as e:
            log(f"Video stop error: {e}")

        vid = None

    if player:
        try:
            if hasattr(player, "stop"):
                player.stop()
            else:
                player.pause()
        except Exception as e:
            log(f"Player stop error: {e}")

        player = None

    if gameProcess:
        try:
            retroArch.quitRetroArchGracefully()
        except Exception as e:
            log(f"RetroArch stop error: {e}")

        gameProcess = None

    comm.sendArtwork(
        os.path.join(cwd, DEFAULT_ARTWORK)
    )

    comm.setTitle(
        "Insert Cartridge"
    )

    comm.sendListText(
        [""] * 5
    )

    log("Remove complete")


def handleStateChange(data):
    global lastReportedNFCState

    # Ignore duplicate state reports
    if data.nfcFound == lastReportedNFCState:
        return

    lastReportedNFCState = data.nfcFound

    processStateChange(data)


def main():
    global comm
    global stats
    global lastState
    global reader

    app = NSApplication.sharedApplication() if platform.system() == "Darwin" else None
    log("Starting application")

    tw = threading.Thread(
        target=threadWatcher,
        daemon=True
    )
    tw.start()

    for folder in [
        "music",
        "roms",
        "videos"
    ]:
        path = os.path.join(
            cwd,
            folder
        )

        if not os.path.exists(path):
            os.makedirs(path)

    stats = Stats()
    stats.loadNFCStats()

    log("Creating communicator")
    comm = ESP32Communicator(
        port=ESP32_COM_PORT
    )

    ThreadWatcher["ESP32CommunicatorRead"] = comm._read_thread
    ThreadWatcher["ESP32CommunicatorWrite"] = comm._write_thread
    comm.callback = handleCommunication

    lastState = None

    log("Creating NFC reader")
    reader = NFCReader(
        handleStateChange
    )

    log("Starting NFC listener")
    nfcThread = threading.Thread(
        target=reader.listen,
        daemon=True
    )
    nfcThread.start()
    ThreadWatcher["NFCReaderLoop"] = nfcThread

    if app is not None:
        app.run()
    else:
        threading.Thread.join(tw)

def threadWatcher():
    global ThreadWatcher
    global reader

    while True:
        for name, thread in list(ThreadWatcher.items()):
            if not thread.is_alive():
                log(f"Thread {name} has stopped.")
                del ThreadWatcher[name]
                if name == "ESP32CommunicatorWrite":
                    ThreadWatcher["ESP32CommunicatorWrite"] = comm.restartWriteThread()
                elif name == "ESP32CommunicatorRead":
                    ThreadWatcher["ESP32CommunicatorRead"] = comm.restartReadThread()
                elif name.startswith("NFCReaderLoop"):
                    log("NFC reader loop has stopped. This is critical.")
                    ThreadWatcher["NFCReaderLoop"] = threading.Thread(
                        target=reader.listen,
                        daemon=True
                    )
                    ThreadWatcher["NFCReaderLoop"].start()
        time.sleep(5)

if __name__ == "__main__":
    main()
