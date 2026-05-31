
import os
import socket
import subprocess
import datetime

mapping = {
    "z64": {"execPath": r"C:\RetroArch-Win64\retroarch.exe", "core": "mupen64plus_next_libretro.dll", "thumbnail": "N64.jpg","romFolder": "n64"},
    "rvz": {"execPath": r"c:\Users\esteb\Downloads\dolphin-2603a-x64\Dolphin-x64\Dolphin.exe", "core": "", "thumbnail": "GC.png","romFolder": "gc"},
}
ROMS_DIR = os.path.join(os.getcwd(), "roms")


def parseRetroTag(tag):
    parts = tag.split("|", 2)
    if len(parts) == 3:
        if parts[0].strip().lower() != "retro":
            return None
        return parts[1].strip(), parts[2].strip()
    if len(parts) == 2:
        return None, parts[1].strip()
    return None

def getRetroGameInfo(game):
    if game.endswith('.z64'):
        metadata = mapping["z64"]
    elif game.endswith('.rvz'):
        metadata = mapping["rvz"]

    return {
        "title": game.split(".")[0],
        "artwork": os.path.join(ROMS_DIR, "thumbnails", metadata["thumbnail"])
    }


def getPrettyTimeDiff(past_time):
    now = datetime.datetime.now()
    diff = now - past_time

    seconds = diff.total_seconds()
    if seconds < 60:
        return f"{int(seconds)} seconds ago"
    minutes = seconds / 60
    if minutes < 60:
        return f"{int(minutes)} minutes ago"
    hours = minutes / 60
    if hours < 24:
        return f"{int(hours)} hours ago"
    days = hours / 24
    return f"{int(days)} days ago"

def launchGame(game):
    if game.endswith('.z64'):
        launchGamePath = mapping["z64"]["execPath"]
        core = mapping["z64"]["core"]
        thumbnail = mapping["z64"]["thumbnail"]
        romsubfolder = mapping["z64"]["romFolder"]
    if game.endswith('.rvz'):
        launchGamePath = mapping["rvz"]["execPath"]
        core = mapping["rvz"]["core"]
        thumbnail = mapping["rvz"]["thumbnail"]
        romsubfolder = mapping["rvz"]["romFolder"]

    
    core_path = core if os.path.isabs(core) else os.path.join(os.path.dirname(launchGamePath), "cores", core)
    rom_path = game if os.path.isabs(game) else os.path.join(ROMS_DIR, romsubfolder, game)

    if not os.path.exists(launchGamePath):
        raise FileNotFoundError(f"RetroArch not found: {launchGamePath}")
    if not os.path.exists(rom_path):
        raise FileNotFoundError(f"ROM not found: {rom_path}")


    if game.endswith('.z64'):
        subprocessCommand = [launchGamePath, "-L", core_path, "-f", rom_path]
    if game.endswith('.rvz'):
        subprocessCommand = [launchGamePath, "-C", "Dolphin.Display.Fullscreen=True", "-b", "-e", rom_path]

    return subprocess.Popen(subprocessCommand)


def quitRetroArchGracefully():
    # RetroArch's default network command port
    ip = "127.0.0.1"
    port = 55355
    message = "QUIT\n"
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(message.encode(), (ip, port))
    sock.close()