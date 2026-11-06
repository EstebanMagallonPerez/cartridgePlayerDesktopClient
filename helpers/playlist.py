import json
import os
import re
import shutil
import tempfile
import unicodedata

import yt_dlp


music_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "music"
)
INDEX_FILE = os.path.join(music_dir, "index.json")
SETTINGS_FILE = os.path.join(music_dir, "settings.json")


def sanitizePlaylistData(data):
    if not isinstance(data, dict):
        return data

    sanitized = dict(data)
    tracks = []
    for track in data.get("tracks", []):
        if not isinstance(track, dict):
            continue
        if track.get("title") is None or track.get("file") is None:
            continue
        sanitized_track = dict(track)
        sanitized_track["index"] = len(tracks)
        tracks.append(sanitized_track)

    sanitized["tracks"] = tracks
    return sanitized


def loadIndex():
    if not os.path.exists(INDEX_FILE):
        return {}
    with open(INDEX_FILE, "r", encoding="utf-8") as index_file:
        return json.load(index_file)


index = loadIndex()


def ensureMusicDir():
    os.makedirs(music_dir, exist_ok=True)


def saveIndex(index_data):
    ensureMusicDir()
    with open(INDEX_FILE, "w", encoding="utf-8") as index_file:
        json.dump(index_data, index_file, indent=2)


def loadSettings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as settings_file:
            return json.load(settings_file)
    except (OSError, json.JSONDecodeError):
        return {"volume": 0.5}


def saveSettings(settings):
    ensureMusicDir()
    with open(SETTINGS_FILE, "w", encoding="utf-8") as settings_file:
        json.dump(settings, settings_file, indent=2)


def getJSRuntime():
    runtimes = {}
    for runtime in ("deno", "node", "bun", "quickjs"):
        path = shutil.which(runtime)
        if path:
            runtimes[runtime] = {"path": path}
    return runtimes or {"deno": {}}


def _normalizedTrackName(value):
    return unicodedata.normalize("NFKC", value).casefold()


def find_audio_file(folder, title, file_name=None):
    expected_names = set()
    if title:
        expected_names.add(_normalizedTrackName(title))
    if file_name:
        expected_names.add(
            _normalizedTrackName(os.path.splitext(file_name)[0])
        )
    if not expected_names or not os.path.isdir(folder):
        return None

    for filename in os.listdir(folder):
        if filename.lower().endswith(".mp3"):
            stem = os.path.splitext(filename)[0]
            if _normalizedTrackName(stem) in expected_names:
                return os.path.join(folder, filename)
    return None


def _playlistHasAudio(folder, playlist_data):
    tracks = [
        track for track in playlist_data.get("tracks", [])
        if isinstance(track, dict) and track.get("title") and track.get("file")
    ]
    return bool(tracks) and all(
        find_audio_file(folder, track["title"], track["file"])
        for track in tracks
    )


def clean(name):
    return re.sub(r'[<>:"/\\|?*]', "", name)


def resolveMetadata(info):
    artist = info.get("playlist_uploader") or info.get("uploader")
    release_date = None
    for entry in info.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        artist = entry.get("playlist_uploader") or entry.get("uploader") or artist
        release_date = entry.get("upload_date") or release_date
        if (
            isinstance(release_date, str)
            and len(release_date) == 8
            and release_date.isdigit()
        ):
            release_date = (
                f"{release_date[:4]}-{release_date[4:6]}-"
                f"{release_date[6:8]}"
            )
        if artist or release_date:
            break
    return artist, release_date


def downloadPlaylist(url, download_dir=music_dir):
    if url in index:
        folder_name = index[url]
        playlist_folder = (
            folder_name
            if os.path.isabs(folder_name)
            else os.path.join(download_dir, folder_name)
        )
        playlist_path = os.path.join(playlist_folder, "playlist.json")
        if os.path.exists(playlist_path):
            with open(playlist_path, "r", encoding="utf-8") as playlist_file:
                cached = json.load(playlist_file)
            if (
                cached.get("playlist_title", "").startswith("Album -")
                and _playlistHasAudio(playlist_folder, cached)
            ):
                return cached

    os.makedirs(download_dir, exist_ok=True)
    temp_dir = tempfile.mkdtemp(prefix="yt_dlp_", dir=download_dir)
    archive_path = os.path.join(temp_dir, "downloaded.txt")
    options = {
        "js_runtimes": getJSRuntime(),
        "remote_components": ["ejs:github"],
        "quiet": True,
        "format": "bestaudio/best",
        "outtmpl": os.path.join(temp_dir, "%(title)s.%(ext)s"),
        "download_archive": archive_path,
        "ignoreerrors": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            },
            {"key": "EmbedThumbnail"},
        ],
        "writethumbnail": True,
    }

    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=True)
        if not isinstance(info, dict):
            raise RuntimeError(f"yt-dlp returned no playlist metadata for {url}")

        title = info.get("title") or "playlist"
        folder_name = index.get(url) or clean(title)
        playlist_folder = (
            folder_name
            if os.path.isabs(folder_name)
            else os.path.join(download_dir, folder_name)
        )
        os.makedirs(playlist_folder, exist_ok=True)

        if os.path.exists(archive_path):
            shutil.move(archive_path, os.path.join(playlist_folder, "downloaded.txt"))
        for filename in os.listdir(temp_dir):
            source = os.path.join(temp_dir, filename)
            target = os.path.join(playlist_folder, filename)
            if os.path.exists(target):
                os.remove(target)
            shutil.move(source, target)

        tracks = []
        for track_index, entry in enumerate(info.get("entries") or []):
            if not isinstance(entry, dict):
                tracks.append({
                    "index": track_index,
                    "title": None,
                    "file": None,
                    "status": "missing",
                })
                continue

            track_title = entry.get("title")
            expected_file = f"{track_title}.mp3" if track_title else None
            audio_path = find_audio_file(
                playlist_folder,
                track_title,
                expected_file
            )
            tracks.append({
                "index": track_index,
                "title": track_title,
                "file": os.path.basename(audio_path) if audio_path else expected_file,
                "status": "downloaded" if audio_path else "failed",
            })

        artist, release_date = resolveMetadata(info)
        metadata = {
            "playlist_title": title,
            "artist": artist,
            "release_date": release_date,
            "tracks": tracks,
        }
        with open(
            os.path.join(playlist_folder, "playlist.json"),
            "w",
            encoding="utf-8"
        ) as playlist_file:
            json.dump(metadata, playlist_file, indent=2)
        return metadata
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def handlePlaylist(url):
    metadata = sanitizePlaylistData(downloadPlaylist(url, music_dir))
    folder_name = index.get(url)
    if folder_name is None:
        folder_name = clean(metadata["playlist_title"])
        index[url] = folder_name
        saveIndex(index)
    if not os.path.isabs(folder_name):
        folder_name = os.path.join(music_dir, folder_name)
    metadata["playlist_folder"] = folder_name
    return metadata
