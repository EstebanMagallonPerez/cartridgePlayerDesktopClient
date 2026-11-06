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

        if (sw1, sw2) != (0x90, 0x00):
            raise RuntimeError(
                f"Read failed ({sw1:02X} {sw2:02X})"
            )

        return data

    # -----------------------------
    # Extract NDEF TLV
    # -----------------------------
    def extractNdef(self, data):

        for i in range(len(data)):

            # Look for NDEF TLV
            if data[i] != 0x03:
                continue

            if i + 2 >= len(data):
                return None

            length = data[i + 1]

            if length == 0xFF:

                if i + 4 >= len(data):
                    continue

                length = (
                    (data[i + 2] << 8) |
                    data[i + 3]
                )

                start = i + 4

            else:
                start = i + 2

            end = start + length

            if end > len(data):
                continue

            # Validate NDEF header
            header = data[start]

            # Valid NDEF header:
            # MB must be set, TNF must not be reserved
            if (header & 0x80) == 0:
                continue

            tnf = header & 0x07

            if tnf == 0x00 or tnf == 0x06:
                continue

            return data[start:end]

        return None

    # -----------------------------
    # Parse NDEF (text record)
    # -----------------------------
    def parseNdef(self, ndef):

        print("PARSING:", list(ndef[:10]))

        if len(ndef) < 7:
            return None

        i = 0

        header = ndef[i]
        i += 1

        sr = (header & 0x10) != 0

        type_length = ndef[i]
        i += 1

        if sr:
            payload_length = ndef[i]
            i += 1
        else:
            payload_length = (
                (ndef[i] << 24)
                | (ndef[i + 1] << 16)
                | (ndef[i + 2] << 8)
                | ndef[i + 3]
            )
            i += 4

        record_type = bytes(ndef[i:i + type_length]).decode("ascii")
        i += type_length

        print("record_type:", record_type)

        if record_type != "T":
            return None

        payload = bytes(ndef[i:i + payload_length])
        print("payload:", payload)

        if not payload:
            return None

        status = payload[0]
        language_length = status & 0x3F

        return payload[1 + language_length:].decode(
            "utf-8",
            errors="ignore"
        )

    # -----------------------------
    # Process tag
    # -----------------------------
    def processTag(self):

        raw = []

        page = 4

        while page < 256:

            raw.extend(self.readPages(page, 4))

            ndef = self.extractNdef(raw)
            print("EXTRACTED NDEF:", list(ndef) if ndef else None)

            if ndef is not None:
                break

            page += 4

        print("rawnfc:", raw)

        if ndef is None:
            self.currentData = None
            return

        self.currentData = self.parseNdef(ndef)

        print("NDEF:", ndef)

        if ndef:
            print("Header:", hex(ndef[0]))
            print("Type Length:", ndef[1])
            print("Payload Length:", ndef[2])

    # -----------------------------
    # Main loop
    # -----------------------------
    def listen(self):
        print("NFC reader loop started")
        while True:
            time.sleep(1)
            try:
                if not self.nfcFound:
                    self.reader.connect()
                    self.reader.mute_buzzer()
                    self.reader.connection.transmit(
                        [0xFF, 0xCA, 0x00, 0x00, 0x00]
                    )
                    self.processTag()
                    self.nfcFound = True
                    self.stateChangeCallback(self)

                else:
                    # Wait until the card disappears
                    try:
                        self.reader.connection.transmit(
                            [0xFF, 0xCA, 0x00, 0x00, 0x00]
                        )
                    except Exception as e:
                        print(f"NFC reader error: {e} PROBABLY removed the nfc tag?")
                        self.nfcFound = False
                        self.currentData = None
                        self.stateChangeCallback(self)
                time.sleep(0.1)

            except Exception as e:
                print(f"NFC reader error: {e} PROBABLY FAILED TO CONNECT TO READER?")
                if self.nfcFound:
                    self.nfcFound = False
                    self.currentData = None
                    self.stateChangeCallback(self)
                time.sleep(0.2)
        print("NFC reader loop exited THIS IS BAD")
