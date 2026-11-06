import json
import os
import sys
import time
import objc
from Cocoa import NSApplication, NSObject, NSURL, NSImage, NSSize, NSTimer
from PyObjCTools import AppHelper
from AVFoundation import AVAudioPlayer
from helpers.playlist import find_audio_file, handlePlaylist, loadSettings
from MediaPlayer import (
    MPNowPlayingInfoCenter,
    MPRemoteCommandCenter,
    MPMediaItemArtwork,
    MPMediaItemPropertyArtwork,
    MPMediaItemPropertyTitle,
    MPMediaItemPropertyArtist,
    MPMediaItemPropertyAlbumTitle,
    MPMediaItemPropertyPlaybackDuration,
    MPNowPlayingInfoPropertyElapsedPlaybackTime,
    MPNowPlayingInfoPropertyPlaybackRate,
    MPNowPlayingPlaybackStatePlaying,
    MPNowPlayingPlaybackStatePaused,
    MPRemoteCommandHandlerStatusSuccess
)

class AudioPlayerDelegate(NSObject):
    def init(self):
        self = objc.super(AudioPlayerDelegate, self).init()
        if self:
            self.player = None
            self.playing = False
            self.artwork_image = None
            self.settings = {"volume": 0.5}
            self.volume = 0.5
            self.playback_timer = None
            self.remote_command_targets = []
            self.track_change_callback = None
        return self

    def setup_audio_and_metadata(
        self,
        album_path=None,
        start_index=0,
        start_playback=True,
        schedule_timer=True
    ):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        if album_path is None:
            album_path = os.path.join(
                script_dir,
                "..",
                "music",
                "Album - Graduation"
            )
        self.album_path = os.path.abspath(album_path)
        playlist_path = os.path.join(
            self.album_path,
            "playlist.json"
        )
        with open(playlist_path, "r", encoding="utf-8") as metadata_file:
            playlist_metadata = json.load(metadata_file)
        self.playlist_metadata = playlist_metadata
        self.tracks = playlist_metadata.get("tracks", [])
        if not self.tracks:
            raise ValueError(f"No tracks found in {playlist_path}")
        self.track_index = start_index % len(self.tracks)
        mp3_path = None
        for offset in range(len(self.tracks)):
            candidate_index = (start_index + offset) % len(self.tracks)
            candidate_track = self.tracks[candidate_index]
            mp3_path = find_audio_file(
                self.album_path,
                candidate_track.get("title"),
                candidate_track.get("file")
            )
            if mp3_path:
                self.track_index = candidate_index
                break
        if mp3_path is None:
            raise FileNotFoundError(
                f"No downloaded MP3 tracks found in {self.album_path}"
            )
        track_metadata = self.tracks[self.track_index]
        jpg_path = os.path.join(
            self.album_path,
            f"{os.path.basename(self.album_path)}.jpg"
        )

        file_url = NSURL.fileURLWithPath_(mp3_path)
        error = None
        self.player, error = AVAudioPlayer.alloc().initWithContentsOfURL_error_(file_url, None)

        if error:
            print(f"Failed to load audio: {error}")
            sys.exit(1)

        self.settings = loadSettings()
        self.volume = max(0.0, min(1.0, float(self.settings.get("volume", 0.5))))

        self.player.setVolume_(self.volume)
        self.player.prepareToPlay()
        if start_playback:
            self.play()

        AppHelper.callAfter(self.registerRemoteCommands)

        artwork = None
        if os.path.exists(jpg_path):
            self.artwork_image = NSImage.alloc().initByReferencingFile_(jpg_path)
            if self.artwork_image and self.artwork_image.isValid():
                def artwork_handler(size):
                    return self.artwork_image

                bounding_size = NSSize(600, 600)
                artwork = MPMediaItemArtwork.alloc().initWithBoundsSize_requestHandler_(bounding_size, artwork_handler)

        center = MPNowPlayingInfoCenter.defaultCenter()

        now_playing_dict = {
            MPMediaItemPropertyTitle: track_metadata.get(
                "title",
                os.path.splitext(os.path.basename(mp3_path))[0]
            ),
            MPMediaItemPropertyArtist: playlist_metadata.get(
                "artist",
                "Unknown Artist"
            ),
            MPMediaItemPropertyAlbumTitle: playlist_metadata.get(
                "playlist_title",
                os.path.basename(os.path.dirname(mp3_path))
            ),
            MPMediaItemPropertyPlaybackDuration: float(self.player.duration()),
            MPNowPlayingInfoPropertyElapsedPlaybackTime: float(self.player.currentTime()),
            MPNowPlayingInfoPropertyPlaybackRate: 1.0 if self.player.isPlaying() else 0.0,
        }

        if artwork:
            now_playing_dict[MPMediaItemPropertyArtwork] = artwork
        center.setNowPlayingInfo_(now_playing_dict)
        center.setPlaybackState_(
            MPNowPlayingPlaybackStatePlaying
            if self.player.isPlaying()
            else MPNowPlayingPlaybackStatePaused
        )
        if schedule_timer:
            self.playback_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                0.5,
                self,
                "playerLoop:",
                None,
                True
            )

    @objc.python_method
    def registerRemoteCommands(self):
        command_center = MPRemoteCommandCenter.sharedCommandCenter()

        command_handlers = (
            (command_center.playCommand(), self.handlePlayCommand_),
            (command_center.pauseCommand(), self.handlePauseCommand_),
            (command_center.nextTrackCommand(), self.handleNextTrackCommand_),
            (command_center.previousTrackCommand(), self.handlePreviousTrackCommand_),
        )
        for command, handler in command_handlers:
            target = command.addTargetWithHandler_(
                lambda event, handler=handler: handler(event)
            )
            self.remote_command_targets.append((command, target))
            command.setEnabled_(True)

    @objc.python_method
    def unregisterRemoteCommands(self):
        for command, target in self.remote_command_targets:
            command.removeTarget_(target)
        self.remote_command_targets.clear()

    def handlePlayCommand_(self, event):
        if self.player and not self.player.isPlaying():
            self.resume()
            print("Remote: Play")
        return MPRemoteCommandHandlerStatusSuccess

    def handlePauseCommand_(self, event):
        if self.player and self.player.isPlaying():
            self.pause()
            print("Remote: Pause")
        return MPRemoteCommandHandlerStatusSuccess

    def handleNextTrackCommand_(self, event):
        self.next()
        return MPRemoteCommandHandlerStatusSuccess

    def handlePreviousTrackCommand_(self, event):
        self.prev()
        return MPRemoteCommandHandlerStatusSuccess

    def change_track(self, offset):
        for step in range(1, len(self.tracks) + 1):
            candidate_index = (
                self.track_index + offset * step
            ) % len(self.tracks)
            track = self.tracks[candidate_index]
            mp3_path = find_audio_file(
                self.album_path,
                track.get("title"),
                track.get("file")
            )
            if mp3_path:
                self.track_index = candidate_index
                break
        else:
            print(f"No downloaded MP3 found in {self.album_path}")
            return

        file_url = NSURL.fileURLWithPath_(mp3_path)
        next_player, error = AVAudioPlayer.alloc().initWithContentsOfURL_error_(
            file_url,
            None
        )
        if error or next_player is None:
            print(f"Failed to load track: {error or mp3_path}")
            return

        next_player.setVolume_(self.volume)
        next_player.prepareToPlay()
        was_playing = self.playing
        self.player.stop()
        self.player = next_player
        if was_playing:
            self.player.play()
            self.playing = bool(self.player.isPlaying())
        else:
            self.playing = False

        self.update_now_playing_for_track(track)
        if self.track_change_callback is not None:
            self.track_change_callback(self.track_index)
        print(f"Now playing: {track.get('title', track['file'])}")

    def update_now_playing_for_track(self, track):
        center = MPNowPlayingInfoCenter.defaultCenter()
        info = dict(center.nowPlayingInfo() or {})
        info[MPMediaItemPropertyTitle] = track.get(
            "title",
            os.path.splitext(track["file"])[0]
        )
        info[MPMediaItemPropertyArtist] = self.playlist_metadata.get(
            "artist",
            "Unknown Artist"
        )
        info[MPMediaItemPropertyAlbumTitle] = self.playlist_metadata.get(
            "playlist_title",
            os.path.basename(self.album_path)
        )
        info[MPMediaItemPropertyPlaybackDuration] = float(self.player.duration())
        info[MPNowPlayingInfoPropertyElapsedPlaybackTime] = float(self.player.currentTime())
        info[MPNowPlayingInfoPropertyPlaybackRate] = (
            1.0 if self.player.isPlaying() else 0.0
        )
        center.setNowPlayingInfo_(info)
        center.setPlaybackState_(
            MPNowPlayingPlaybackStatePlaying
            if self.player.isPlaying()
            else MPNowPlayingPlaybackStatePaused
        )

    def play(self):
        if self.player:
            self.player.prepareToPlay()
            self.playing = bool(self.player.play())
            self.update_playback_rate(1.0 if self.playing else 0.0)

    def pause(self):
        if self.player:
            self.player.pause()
            self.playing = False
            self.update_playback_rate(0.0)

    def resume(self):
        self.play()

    @objc.python_method
    def applyVolume(self, new_volume):
        self.volume = max(0.0, min(1.0, float(new_volume)))
        if self.player:
            self.player.setVolume_(self.volume)
        self.settings["volume"] = self.volume
        settings_path = os.path.join(
            os.path.dirname(self.album_path),
            "settings.json"
        )
        with open(settings_path, "w", encoding="utf-8") as settings_file:
            json.dump(self.settings, settings_file, indent=2)

    @objc.python_method
    def increaseVolume(self, step=0.02):
        self.applyVolume(self.volume + step)

    @objc.python_method
    def decreaseVolume(self, step=0.02):
        self.applyVolume(self.volume - step)

    def next(self):
        self.change_track(1)

    def prev(self):
        self.change_track(-1)

    def toggle(self):
        if self.player and self.player.isPlaying():
            self.pause()
        else:
            self.resume()

    def playerLoop_(self, timer):
        if not self.player:
            return
        if self.playing and not self.player.isPlaying():
            self.next()
        elif self.player.isPlaying():
            self.update_playback_rate(1.0)

    def update_playback_rate(self, rate):
        center = MPNowPlayingInfoCenter.defaultCenter()
        info = dict(center.nowPlayingInfo() or {})
        info[MPNowPlayingInfoPropertyPlaybackRate] = float(rate)
        info[MPNowPlayingInfoPropertyElapsedPlaybackTime] = float(self.player.currentTime())
        center.setNowPlayingInfo_(info)
        center.setPlaybackState_(
            MPNowPlayingPlaybackStatePlaying
            if rate > 0
            else MPNowPlayingPlaybackStatePaused
        )


class MusicPlayer:
    def __init__(self, url, comm):
        self.url = url
        self.comm = comm
        self.alive = True

        music_root = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "music"
        )
        playlist_data = handlePlaylist(url)
        if not isinstance(playlist_data, dict) or not playlist_data.get("playlist_folder"):
            raise ValueError(f"Could not load or download playlist for URL: {url}")

        playlist_folder = playlist_data["playlist_folder"]
        self.folder = (
            playlist_folder
            if os.path.isabs(playlist_folder)
            else os.path.join(music_root, playlist_folder)
        )
        with open(
            os.path.join(self.folder, "playlist.json"),
            "r",
            encoding="utf-8"
        ) as playlist_file:
            playlist_metadata = json.load(playlist_file)
        self.playlist_title = playlist_metadata.get(
            "playlist_title",
            os.path.basename(self.folder)
        )

        self.delegate = AudioPlayerDelegate.alloc().init()
        self.delegate.track_change_callback = self.updateExternalNowPlaying
        self.delegate.setup_audio_and_metadata(
            self.folder,
            start_index=0,
            start_playback=False,
            schedule_timer=False
        )

    @property
    def index(self):
        return self.delegate.track_index

    def play(self):
        self.delegate.play()
        self.playing = bool(
            self.delegate.player and self.delegate.player.isPlaying()
        )

    def pause(self):
        self.delegate.pause()
        self.playing = False

    def stop(self):
        self.alive = False
        self.pause()
        AppHelper.callAfter(self.delegate.unregisterRemoteCommands)

    def resume(self):
        self.delegate.resume()

    def toggle(self):
        if self.delegate.playing:
            self.pause()
        else:
            self.resume()

    def next(self):
        self.delegate.next()

    def prev(self):
        self.delegate.prev()

    def updateExternalNowPlaying(self, track_index):
        self.comm.updateNowPlaying(
            self.folder,
            current_index=track_index
        )

    def increaseVolume(self):
        self.delegate.increaseVolume()

    def decreaseVolume(self):
        self.delegate.decreaseVolume()

    def playerLoop(self):
        self.play()
        while self.alive:
            if not self.delegate.player:
                break
            if self.delegate.playing and not self.delegate.player.isPlaying():
                self.next()
            elif self.delegate.player.isPlaying():
                self.delegate.update_playback_rate(1.0)
            time.sleep(0.5)

        self.pause()

if __name__ == "__main__":
    app = NSApplication.sharedApplication()

    delegate = AudioPlayerDelegate.alloc().init()
    delegate.setup_audio_and_metadata()

    print("Application loop running. Press Ctrl+C in terminal to exit.")
    app.run()
