from py_acr122u import nfc
import time

class NFCReader:

    def __init__(self, stateChangeCallback):
        self.reader = nfc.Reader()
        self.stateChangeCallback = stateChangeCallback
        self.nfcFound = False
        self.currentData = None

    # -----------------------------
    # Read pages
    # -----------------------------
    def readPages(self, start, count):
        data, sw1, sw2 = self.reader.connection.transmit(
            [0xFF, 0xB0, 0x00, start, count * 4]
        )
        return data

    # -----------------------------
    # Extract NDEF TLV
    # -----------------------------
    def extractNdef(self, data):
        i = 0
        while i < len(data):
            if data[i] == 0x03:
                length = data[i + 1]

                if length == 0xFF:
                    length = (data[i + 2] << 8) | data[i + 3]
                    start = i + 4
                else:
                    start = i + 2

                return data[start:start + length]

            elif data[i] == 0xFE:
                break

            else:
                i += 1

        return None

    # -----------------------------
    # Parse NDEF (text record)
    # -----------------------------
    def parseNdef(self, ndef):
        i = 0
        header = ndef[i]
        i += 1
        type_length = ndef[i]
        i += 1
        sr = (header & 0x10) != 0
        if sr:
            payload_length = ndef[i]
            i += 1
        else:
            payload_length = (
                (ndef[i] << 24) |
                (ndef[i+1] << 16) |
                (ndef[i+2] << 8) |
                (ndef[i+3])
            )
            i += 4
        type_field = chr(ndef[i])
        i += type_length
        payload = ndef[i:i + payload_length]

        # Text record only (T)
        if type_field == 'T':
            status = payload[0]
            lang_len = status & 0x3F
            text = bytes(payload[1 + lang_len:]).decode('utf-8', errors='ignore')
            return text

        return None

    # -----------------------------
    # Process tag
    # -----------------------------
    def processTag(self):
        raw = []
        for start in range(4, 32, 4):
            raw += self.readPages(start, 4)
        ndef = self.extractNdef(raw)

        if ndef:
            result = self.parseNdef(ndef)
            self.currentData = result

    # -----------------------------
    # Main loop
    # -----------------------------
    def listen(self):
        while True:
            try:
                self.reader.connect()
                self.reader.mute_buzzer()
                if not self.nfcFound:
                    self.reader.connection.transmit(
                        [0xFF, 0xCA, 0x00, 0x00, 0x00]
                    )
                    self.processTag()
                    self.nfcFound = True
                    self.stateChangeCallback(self)
            except Exception:
                self.nfcFound = False
                self.currentData = None
                self.stateChangeCallback(self)
                time.sleep(0.2)
