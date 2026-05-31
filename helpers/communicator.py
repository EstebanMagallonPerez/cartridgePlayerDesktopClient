import serial
import threading
import time
import json
import os
from PIL import Image, ImageDraw
from helpers.music import sanitizePlaylistData

class ESP32Communicator:

    CHUNK_SIZE = 256

    def __init__(self, port="COM9", baud=115200, auto_connect=True):
        self.port = port
        self.baud = baud
        self.ser = None
        self._read_thread = None
        self._read_running = False
        self.callback = None

        self.sendQueue = []
        t1 = threading.Thread(target=self.handleQueue, daemon=True)
        t1.start()

        if auto_connect:
            self.connect()
            self.startReadThread()
        

    # ---------------- SERIAL ---------------- #
    def addToQueue(self, opcode, payload=b""):
        self.sendQueue.append((opcode, payload))

    def handleQueue(self):
        while True:
            if self.sendQueue:
                packet = self.sendQueue.pop(0)
                self.sendPacket(*packet)
            time.sleep(0.01)  # small delay for stability
    def setCallback(self,callback):
        self.callback = callback

    def connect(self):
        self.ser = serial.Serial(self.port, self.baud, timeout=1)
        time.sleep(2)  # allow ESP32 reset
        if not self._read_running:
            self.startReadThread()

    def close(self):
        self.stopReadThread()
        if self.ser and self.ser.is_open:
            self.ser.close()

    def __del__(self):
        self.close()

    def startReadThread(self):
        if self._read_thread and self._read_thread.is_alive():
            return
        self._read_running = True
        self._read_thread = threading.Thread(target=self._readLoop, daemon=True)
        self._read_thread.start()

    def stopReadThread(self):
        self._read_running = False
        if self._read_thread:
            self._read_thread.join(timeout=2)
            self._read_thread = None

    def _readLoop(self):
        while self._read_running:
            try:
                if not self.ser or not self.ser.is_open:
                    time.sleep(0.1)
                    continue

                data = self.ser.read(self.ser.in_waiting or 1)
                if data:
                    try:
                        message = data.decode("utf-8", errors="replace")
                    except Exception:
                        message = repr(data)
                    self.callback(message)
                else:
                    time.sleep(0.05)
            except Exception:
                time.sleep(0.2)

    def sendPacket(self, opcode, payload=b""):
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        length = len(payload)
        packet = bytearray()
        packet.append(opcode)
        packet += length.to_bytes(2, "big")
        packet += payload
        self.ser.write(packet)

    # ---------------- IMAGE ---------------- #

    def image_to_floyd_steinberg_1bit(self, path):
        base, _ = os.path.splitext(path)
        bmp_path = base + "_fs.bmp"

        if os.path.exists(bmp_path):
            bw = Image.open(bmp_path).convert("1")
        else:
            img = Image.open(path).convert("L")
            img = img.resize((256, 256))

            radius = 20
            bw = img.convert("1")
            pixels = bw.load()

            for y in range(256):
                if y < radius:
                    offset = radius - int((radius * radius - (radius - y) ** 2) ** 0.5)
                    for x in range(offset):
                        pixels[x, y] = 255
                elif y >= 256 - radius:
                    offset = radius - int((radius * radius - (y - (256 - radius)) ** 2) ** 0.5)
                    for x in range(offset):
                        pixels[x, y] = 255

            bw.save(bmp_path)
            print(f"Saved debug BMP: {bmp_path}")

        pixels = bw.load()
        data = bytearray()

        for y in range(256):
            byte = 0
            bit_count = 0

            for x in range(256):
                pixel = pixels[x, y]

                bit = 0 if pixel else 1
                byte = (byte << 1) | bit
                bit_count += 1

                if bit_count == 8:
                    data.append(byte)
                    byte = 0
                    bit_count = 0

            if bit_count > 0:
                byte <<= (8 - bit_count)
                data.append(byte)

        return data
    def sendArtwork(self, path):
        data = self.image_to_floyd_steinberg_1bit(path)

        self.addToQueue(0x05)  # START

        for i in range(0, len(data), self.CHUNK_SIZE):
            self.addToQueue(0x06, data[i:i+self.CHUNK_SIZE])

        self.addToQueue(0x07)  # END

    # ---------------- PLAYLIST ---------------- #

    def loadPlaylist(self, json_path):
        if not os.path.exists(json_path):
            raise FileNotFoundError(f"Playlist file not found: {json_path}")


        with open(json_path, "r", encoding="utf-8") as f:
            data = sanitizePlaylistData(json.load(f))

        if "playlist_title" not in data or "tracks" not in data:
            raise ValueError("Invalid playlist JSON format")

        return data

    def getFirstJPG(self, folder):
        for f in os.listdir(folder):
            if f.lower().endswith((".jpg", ".jpeg")):
                return os.path.join(folder, f)
        return None

    def setTitle(self, title):
        self.addToQueue(0x01, title)

    def sendNowPlaying(self, tracks, current_index):
        total = len(tracks)

        start = max(current_index - 2, 0)
        end = min(start + 5, total)

        while (end - start < 5) and start > 0:
            start -= 1

        window = tracks[start:end]

        local_index = current_index - start

        self.sendListText([elem['title'] for elem in window], local_index)

    def sendListText(self, info, current_index=-1):
        data = [str(current_index)]
        for i in range(5):
            data.append(str(i))
            if i < len(info):
                data.append(str(info[i]))
            else:
                data.append("")
        payload = "|".join(data)
        self.addToQueue(0x08, payload)


    def updateNowPlaying(self, folder_path, current_index=0):
        json_path = os.path.join(folder_path, "playlist.json")

        data = self.loadPlaylist(json_path)
        tracks = sorted(data["tracks"], key=lambda x: x["index"])
        self.sendNowPlaying(tracks, current_index)

    def initPlaylist(self, folder_path, current_index=0):
        json_path = os.path.join(folder_path, "playlist.json")

        data = self.loadPlaylist(json_path)
        artwork = self.getFirstJPG(folder_path)

        title = data["playlist_title"].removeprefix("Album - ")
        tracks = sorted(data["tracks"], key=lambda x: x["index"])

        if artwork:
            self.sendArtwork(artwork)
    
        self.setTitle(title)

        self.sendNowPlaying(tracks, current_index)

        print("Playlist sent.")
