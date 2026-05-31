import datetime
import json
import os
import time


class Stats:
    def __init__(self, stats_file=None):
        cwd = os.getcwd()
        self.stats_file = stats_file or os.path.join(cwd, "data", "nfc_stats.json")
        if not os.path.exists(os.path.dirname(self.stats_file)):
            os.makedirs(os.path.dirname(self.stats_file))

        self.nfc_stats = None
        self.current_nfc_tag = None
        self.current_session_start = None
        self.current_session_type = None
        self.current_stats_visible = False


    def loadNFCStats(self):
        if os.path.exists(self.stats_file):
            with open(self.stats_file, "r", encoding="utf-8") as f:
                try:
                    self.nfc_stats = json.load(f)
                except json.JSONDecodeError:
                    self.nfc_stats = {"tags": {}}
        else:
            self.nfc_stats = {"tags": {}}
        return self.nfc_stats

    def saveNFCStats(self):
        with open(self.stats_file, "w", encoding="utf-8") as f:
            json.dump(self.nfc_stats, f, indent=2)

    def getTagStats(self, tag):
        tags = self.nfc_stats.setdefault("tags", {})
        stats = tags.setdefault(
            tag,
            {
                "display_name": tag,
                "type": None,
                "artist": None,
                "release_date": None,
                "playcount": 0,
                "playtime_seconds": 0,
                "last_played": None,
                "info": [],
            },
        )
        return stats

    @staticmethod
    def formatPlaytime(seconds):
        seconds = int(seconds or 0)
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        if hours:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    @staticmethod
    def formatLastPlayed(last_played):
        if not last_played:
            return "Never"
        try:
            dt = datetime.datetime.fromisoformat(last_played)
            return dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return str(last_played)

    def build_stats_info(self, stats):
        lines = []
        if "artist" not in stats:
            lines.append(f"Name: {stats.get('display_name', 'Unknown')}")
            lines.append(f"Type: {stats.get('type') or 'Unknown'}")
        else:
            lines.append(f"Artist: {stats.get('artist') or 'Unknown'}")
            lines.append(f"Release Date: {stats.get('release_date') or 'Unknown'}")
        lines.append(f"Play Count: {stats.get('playcount', 0)}")
        lines.append(
            f"Time: {self.formatPlaytime(stats.get('playtime_seconds', 0))}"
        )
        lines.append(
            f"Last Played: {self.formatLastPlayed(stats.get('last_played'))}"
        )
        return lines

    def beginNFCSession(
        self,
        tag,
        kind,
        display_name=None,
        extra_info=None,
        metadata=None,
    ):
        self.current_nfc_tag = tag
        self.current_session_start = time.time()
        self.current_session_type = kind
        self.current_stats_visible = False

        stats = self.getTagStats(tag)
        stats["type"] = kind
        if display_name:
            stats["display_name"] = display_name
        if extra_info is not None:
            stats["info"] = extra_info
        if metadata is not None:
            if metadata.get("artist"):
                stats["artist"] = metadata.get("artist")
            if metadata.get("release_date"):
                stats["release_date"] = metadata.get("release_date")
        stats["playcount"] = stats.get("playcount", 0) + 1
        stats["last_played"] = datetime.datetime.now().isoformat()
        self.saveNFCStats()

    def endNFCSession(self):
        if not self.current_nfc_tag or self.current_session_start is None:
            self.current_nfc_tag = None
            self.current_session_start = None
            self.current_session_type = None
            return

        stats = self.getTagStats(self.current_nfc_tag)
        elapsed = int(time.time() - self.current_session_start)
        stats["playtime_seconds"] = stats.get("playtime_seconds", 0) + elapsed
        self.saveNFCStats()

        self.current_nfc_tag = None
        self.current_session_start = None
        self.current_session_type = None
