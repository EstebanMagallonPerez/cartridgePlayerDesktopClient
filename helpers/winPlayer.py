import json
import os
import threading
import time

import pygame

from helpers.playlist import (
    handlePlaylist,
    loadSettings,
    music_dir,
    sanitizePlaylistData,
    saveSettings,
)


class MusicPlayer:
    def __init__(self, url, comm):
        pygame.mixer.init()
        metadata = handlePlaylist(url)
        self.folder = os.path.join(music_dir, metadata.get("playlist_folder"))
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
        self.alive = True

        self.setVolume(self.volume)

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
        self.setVolume(self.volume)

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
        pygame.mixer.music.set_volume(self.volume)
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
        self.alive = True
        while self.alive:
            try:
                if not pygame.mixer.music.get_busy() and self.playing:
                    self.next()
                time.sleep(0.5)
            except Exception as e:
                print(f"Error in player loop: {e}")
                time.sleep(1)
        print("Player loop terminated.")
