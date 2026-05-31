import pygame
import json
import threading
import os
import shutil
import tempfile
import time
import yt_dlp
import re
from datetime import datetime

music_dir = os.path.join(os.getcwd(), "music")
INDEX_FILE = os.path.join(music_dir, "index.json")
SETTINGS_FILE = os.path.join(music_dir, "settings.json")


def sanitizePlaylistData(data):
    if not isinstance(data, dict):
        return data

    tracks = data.get("tracks", [])
    sanitized_tracks = []

    for track in tracks:
        if not isinstance(track, dict):
            continue

        title = track.get("title")
        file_name = track.get("file")

        if title is None or file_name is None:
            continue

        sanitized_track = dict(track)
        sanitized_track["index"] = len(sanitized_tracks)
        sanitized_tracks.append(sanitized_track)

    sanitized = dict(data)
    sanitized["tracks"] = sanitized_tracks
    return sanitized


def resolveMetadata(info):
    artist = None
    release_date = None
    for entry in info.get("entries", []):
        try:
            for key in entry:
                if key == "uploader":
                    print("Found uploader field in entry:", entry["uploader"])
                    artist = entry["uploader"]
                if key == "playlist_uploader":
                    print("Found playlist_uploader field in entry:", entry["playlist_uploader"])
                    if entry["playlist_uploader"] != None:
                        artist = entry["playlist_uploader"]
                elif key == "upload_date":
                    release_date = entry["upload_date"]
                    if isinstance(release_date, str) and len(release_date) == 8 and release_date.isdigit():
                        release_date = f"{release_date[0:4]}-{release_date[4:6]}-{release_date[6:8]}"
            return artist, release_date
        except Exception as e:
            artist = info["uploader"]
            release_date = info["modified_date"]
            if isinstance(release_date, str) and len(release_date) == 8 and release_date.isdigit():
                release_date = f"{release_date[0:4]}-{release_date[4:6]}-{release_date[6:8]}"
            print(info["uploader"],"date:", info.get("modified_date"))
            print("Error resolving metadata for entry:", e)
            return artist, release_date

    return artist, release_date

def saveIndex(index):
    ensureMusicDir()
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)


def loadIndex():
    if os.path.exists(INDEX_FILE):
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

index = loadIndex()

def ensureMusicDir():
    os.makedirs(music_dir, exist_ok=True)

def loadSettings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                pass
    return {"volume": 0.5}


def saveSettings(settings):
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


def getJSRuntime():
    runtimes = {}
    deno_paths = [
        r'C:\Users\esteb\.deno\bin\deno.exe',
        os.path.expanduser(r'~/.deno/bin/deno.exe'),
    ]

    for path in deno_paths:
        if path and os.path.isfile(path):
            runtimes['deno'] = {'path': path}
            break

    for runtime in ('deno', 'node', 'bun', 'quickjs'):
        if runtime not in runtimes:
            path = shutil.which(runtime)
            if path:
                runtimes[runtime] = {'path': path}

    return runtimes or {'deno': {}}


def downloadPlaylist(url, music_dir):
    global index
    if url in index:
        playlist_folder = index[url]
        playlist_path = os.path.join(playlist_folder, "playlist.json")
        print("Found existing playlist folder for URL, checking for playlist.json:", playlist_path)
        if os.path.exists(playlist_path):
            with open(playlist_path, "r", encoding="utf-8") as f:
                playlistData = json.load(f)
            if playlistData["playlist_title"].startswith("Album -"):
                return playlistData

    if not os.path.exists(music_dir):
        os.makedirs(music_dir)

    temp_download_dir = tempfile.mkdtemp(prefix='yt_dlp_', dir=music_dir)
    temp_archive_path = os.path.join(temp_download_dir, 'downloaded.txt')

    ydl_opts = {
        'js_runtimes': getJSRuntime(),
        'remote_components': ['ejs:github'],
        'quiet': True,
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(
            temp_download_dir,
            '%(title)s.%(ext)s'
        ),
        'download_archive': temp_archive_path,
        'ignoreerrors': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        },
        {
            'key': 'EmbedThumbnail',
        }],
        'writethumbnail': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    playlist_title = clean(info.get('title', 'playlist'))
    playlist_folder = os.path.join(music_dir, playlist_title)
    os.makedirs(playlist_folder, exist_ok=True)

    if os.path.exists(temp_archive_path):
        shutil.move(temp_archive_path, os.path.join(playlist_folder, 'downloaded.txt'))
    
    for filename in os.listdir(temp_download_dir):
        source_path = os.path.join(temp_download_dir, filename)
        if filename == 'downloaded.txt':
            continue
        target_path = os.path.join(playlist_folder, filename)
        if os.path.exists(target_path):
            os.remove(target_path)
        shutil.move(source_path, target_path)

    try:
        os.rmdir(temp_download_dir)
    except OSError:
        pass

    tracks = []

    for i, entry in enumerate(info.get('entries') or []):
        if not entry:
            tracks.append({
                "index": i,
                "title": None,
                "file": None,
                "status": "missing"
            })
            continue

        title = entry.get("title")
        filename = f"{title}.mp3"

        tracks.append({
            "index": i,
            "title": title,
            "file": filename,
            "status": "downloaded"
        })

    tracks.sort(key=lambda x: x["index"])
    artist,release_date = resolveMetadata(info)

    metadata = {
        "playlist_title": info.get("title", "playlist"),
        "artist": artist,
        "release_date": release_date,
        "tracks": tracks
    }

    with open(os.path.join(playlist_folder, "playlist.json"), "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    return metadata

def clean(name):
    return re.sub(r'[<>:"/\\|?*]', '', name)

def handlePlaylist(url):
    if url in index:
        threading.Thread(
            target=downloadPlaylist,
            args=(url, music_dir,),
            daemon=True
        ).start()

        playlist_folder = index[url]
        playlist_path = os.path.join(playlist_folder, "playlist.json")
        if os.path.exists(playlist_folder):
            with open(playlist_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                data = sanitizePlaylistData(data)
                data["playlist_folder"] = playlist_folder
                return data
        return {}
    else:
        metadata = downloadPlaylist(url, music_dir)
        metadata = sanitizePlaylistData(metadata)
        playlist_folder = os.path.join(music_dir, clean(metadata["playlist_title"]))
        metadata["playlist_folder"] = playlist_folder
        index[url] = playlist_folder
        saveIndex(index)
        return metadata


class MusicPlayer:
    def __init__(self, url, comm):
        pygame.mixer.init()
        metadata = handlePlaylist(url)
        self.folder = metadata.get("playlist_folder")
        self.settings = loadSettings()
        self.comm = comm

        with open(os.path.join(self.folder, "playlist.json")) as f:
            data = sanitizePlaylistData(json.load(f))
        self.playlist_title = data.get("playlist_title")
        self.tracks = data["tracks"]
        if not self.tracks:
            raise Exception("No tracks found in playlist.json — download failed or empty playlist")
        self.index = 0
        self.playing = False
        self.lock = threading.Lock()
        self.volume = self.settings.get("volume", 0.5)

        pygame.mixer.music.setVolume(self.volume)
    
    def loadTrack(self):
        searched = 0
        path = None

        while searched < len(self.tracks):
            track = self.tracks[self.index]
            file_name = track.get("file")
            title = track.get("title")

            if file_name:
                candidate = os.path.join(self.folder, file_name)
                if os.path.exists(candidate):
                    path = candidate
                    break

            if title:
                for filename in os.listdir(self.folder):
                    if filename.endswith('.mp3') and (
                        filename[:-4] == title or filename == file_name
                    ):
                        path = os.path.join(self.folder, filename)
                        break

            if path:
                break

            self.index = (self.index + 1) % len(self.tracks)
            searched += 1

        if not path or not os.path.exists(path):
            raise FileNotFoundError(
                f"No playable track found in playlist '{self.folder}' starting at index {self.index}"
            )

        self.playing = True
        print(f"Now playing: {track.get('title') or 'Unknown Track'}")
        pygame.mixer.music.load(path)
        pygame.mixer.music.setVolume(self.volume)

    def play(self):
        self.loadTrack()
        pygame.mixer.music.play()
        self.playing = True

    def pause(self):
        pygame.mixer.music.pause()
        self.playing = False

    def resume(self):
        pygame.mixer.music.unpause()
        self.playing = True

    def setVolume(self, new_volume):
        self.volume = max(0.0, min(1.0, new_volume))
        pygame.mixer.music.setVolume(self.volume)
        self.settings["volume"] = self.volume
        saveSettings(self.settings)

    def increaseVolume(self, step=0.02):
        self.setVolume(self.volume + step)

    def decreaseVolume(self, step=0.02):
        self.setVolume(self.volume - step)

    def next(self):
        with self.lock:
            self.index = (self.index + 1) % len(self.tracks)
            self.play()

        self.comm.updateNowPlaying(
            self.folder,
            current_index=self.index
        )

    def prev(self):
        with self.lock:
            self.index = (self.index - 1) % len(self.tracks)
            self.play()

        self.comm.updateNowPlaying(
            self.folder,
            current_index=self.index
        )

    def toggle(self):
        if self.playing:
            self.pause()
        else:
            self.resume()

    def playerLoop(self):
        self.play()
        while True:
            if not pygame.mixer.music.get_busy() and self.playing:
                self.next()
            time.sleep(0.5)