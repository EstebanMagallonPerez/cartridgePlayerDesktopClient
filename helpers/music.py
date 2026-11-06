import platform

from helpers.playlist import sanitizePlaylistData

if platform.system() == "Darwin":
    from helpers.macPlayer import MusicPlayer
elif platform.system() == "Windows":
    from helpers.winPlayer import MusicPlayer
else:
    raise RuntimeError(
        f"Unsupported operating system for music playback: {platform.system()}"
    )

__all__ = ["MusicPlayer", "sanitizePlaylistData"]
