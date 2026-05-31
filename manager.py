import json
import os
import threading
import time
from helpers.stats import Stats
from helpers.music import MusicPlayer
from helpers.reader import NFCReader
from helpers.communicator import ESP32Communicator
from helpers import retroArch
from pyvidplayer2 import Video

ESP32_COM_PORT = "COM14"
DEFAULT_VIDEO_PATH = "./videos/bbb.mp4"
DEFAULT_ARTWORK = "./data/icon.png"

cwd = os.getcwd()
player = None
gameProcess = None
vid = None
comm = None
lastState = None

def displayCurrentStats():
    if not stats.current_nfc_tag:
        print("No current NFC tag to display stats for")
        return

    tag_stats = stats.getTagStats(stats.current_nfc_tag)
    comm.sendListText(stats.build_stats_info(tag_stats))
    stats.current_stats_visible = True

def restoreCurrentView():
    if not stats.current_nfc_tag:
        return

    if stats.current_session_type == "music" and player is not None:
        comm.updateNowPlaying(player.folder, current_index=player.index)

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
        if player is not None:
            try:
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
                else:
                    print("Unknown command from ESP32:", repr(opcode))
            except Exception as exc:
                print("Error handling command:", exc)
        elif vid:
            if opcode == "0":
                vid.seek(-5)
            elif opcode == "1":
                if not vid.paused:
                    vid.pause()
                else:
                    vid.resume()
            elif opcode == "2":
                vid.seek(5)
        elif gameProcess is not None:
            # When a retro game is running, allow toggling stats view via opcode 4
            if opcode == "4":
                toggleCurrentStats()
            else:
                print("Unknown command from ESP32 (game):", repr(opcode))


def launchVideo(video_path):
    global vid
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")
    vid = Video(video_path)
    vid.preview()

def handleStateChange(data):
    global player, gameProcess, vid, lastState

    if data.nfcFound:
        if lastState is True:
            return

        print("executing insert cartridge logic")
        lastState = True
        tag = (data.currentData or "").strip()

        if tag.lower().startswith("video|"):
            video_name = tag.split("|", 1)[1].strip()
            stats.beginNFCSession(tag, "video", video_name, ["Video Cartridge"])
            comm.setTitle(video_name)
            threading.Thread(target=launchVideo, args=(DEFAULT_VIDEO_PATH,), daemon=True).start()
            return

        if tag.lower().startswith("retro|"):
            parsed = retroArch.parseRetroTag(tag)
            if parsed:
                console, game = parsed
                print(console, game)
            stats.beginNFCSession(tag, "retro", game, [f"Console: {console}"])
            if game is None:
                game = console

            # Prefer detailed info when a filename with extension is provided
            retro_info = retroArch.getRetroGameInfo(game)

            # send artwork/title if available
            if retro_info:
                comm.sendArtwork(retro_info["artwork"])
                time.sleep(0.15)
                comm.setTitle(retro_info["title"])
                tag_stats = stats.getTagStats(tag)
                comm.sendListText(stats.build_stats_info(tag_stats))

            # attempt to launch the game (may raise if path/format invalid)
            gameProcess = retroArch.launchGame(game)
            return

        player = MusicPlayer(tag, comm)
        print("Music player initialized with URL:", tag)
        playlist_meta = {}
        playlist_path = os.path.join(player.folder, "playlist.json")
        try:
            with open(playlist_path, "r", encoding="utf-8") as f:
                playlist_meta = json.load(f)
        except Exception:
            playlist_meta = {}

        stats.beginNFCSession(
            tag,
            "music",
            player.playlist_title,
            [f"Playlist: {player.playlist_title}"],
            metadata=playlist_meta,
        )
        comm.initPlaylist(player.folder, current_index=0)
        threading.Thread(target=player.playerLoop, daemon=True).start()
        return

    if lastState is False:
        return

    print("executing remove cartridge logic")
    lastState = False

    stats.endNFCSession()

    if vid:
        vid.stop()
        vid = None

    if player is not None:
        player.pause()
        player = None

    if gameProcess:
        retroArch.quitRetroArchGracefully()
        gameProcess = None

    comm.sendArtwork(os.path.join(cwd, DEFAULT_ARTWORK))
    comm.setTitle("Insert Cartridge")
    comm.sendListText([""]*5)


def main():
    global comm, lastState, nfc_stats, stats

    #check if music, roms, and video directories exist, if not create them
    for folder in ["music", "roms", "videos"]:
        path = os.path.join(cwd, folder)
        if not os.path.exists(path):
            os.makedirs(path)

    stats = Stats()
    nfc_stats = stats.loadNFCStats()
    comm = ESP32Communicator(port=ESP32_COM_PORT)
    comm.callback = handleCommunication
    lastState = None

    reader = NFCReader(handleStateChange)
    reader.listen()


if __name__ == "__main__":
    main()

    
    
