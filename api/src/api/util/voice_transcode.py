"""Inbound voice decoding to 16 kHz mono PCM16 (todo 4484).

The Lambda API image is size-limited, so `av` and `soundfile` do not fit. Three
small decoders cover the reachable formats: pysilk-mod for WeChat SILK,
opuslib-next-bundled for Telegram OGG/Opus (with a stdlib RFC 3533 demuxer),
and a minimal RIFF reader for WAV. Anything else is rejected by name, never
guessed at.

Caps are enforced here as well as at the fetch and module boundaries: the
downloaded blob may be at most 4,000,000 bytes, the decoded PCM at most
3,999,956 bytes (4,000,000 once the module adds a WAV header), and the
recording at most 120 seconds. The decoded byte cap is checked after every
Opus packet so a compressed silence bomb cannot expand without bound.
"""

import array
import struct
import sys

SAMPLE_RATE = 16_000
MAX_VOICE_BYTES = 4_000_000
PCM_MAX_BYTES = 3_999_956
MAX_DURATION_MS = 120_000
_PCM_BYTES_PER_MS = SAMPLE_RATE * 2 // 1000
_MAX_PCM_SAMPLES = MAX_DURATION_MS * SAMPLE_RATE // 1000
_PART_BYTES = 1_000_000
_OPUS_FRAME_SAMPLES = 1920  # 120 ms at 16 kHz, the longest allowed packet
_OPUS_RATE = 48_000
_SILK = (b"\x02#!SILK_V3", b"#!SILK_V3")


class VoiceRejected(ValueError):
    """A voice note that cannot be decoded.

    `code` is a closed machine value (`too_large`, `too_long`,
    `unsupported_type`). It never carries audio bytes or a provider URL.
    """

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def transcode(data):
    """Return `(pcm16 mono 16 kHz bytes, duration_ms)` for one voice blob."""
    if not isinstance(data, bytes) or not data:
        raise VoiceRejected("unsupported_type")
    if len(data) > MAX_VOICE_BYTES:
        raise VoiceRejected("too_large")
    if data[:4] == b"OggS":
        pcm = _decode_ogg_opus(data)
    elif data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        pcm = _decode_wav(data)
    elif data.startswith(_SILK):
        pcm = _decode_silk(data)
    else:
        raise VoiceRejected("unsupported_type")
    if len(pcm) % 2:
        pcm = pcm[:-1]
    if not pcm:
        raise VoiceRejected("unsupported_type")
    # The voice module requires 1..120,000 ms; a valid sub-millisecond clip
    # would otherwise finalize with 0 and be rejected there.
    duration_ms = max(1, len(pcm) // _PCM_BYTES_PER_MS)
    if duration_ms > MAX_DURATION_MS:
        raise VoiceRejected("too_long")
    return pcm, duration_ms


def _decode_silk(data):
    import pysilk

    # The decoder expects the leading 0x02 byte; some senders strip it and
    # keep only the bare `#!SILK_V3` magic.
    payload = data if data.startswith(_SILK[0]) else b"\x02" + data
    _check_silk_frames(payload)
    try:
        pcm = pysilk.decode(payload, sample_rate=SAMPLE_RATE)
    except Exception:
        raise VoiceRejected("unsupported_type") from None
    if not isinstance(pcm, bytes):
        raise VoiceRejected("unsupported_type")
    return _cap(pcm)


def _check_silk_frames(data):
    """Walk the length-prefixed frame chain before handing bytes to C++.

    A malformed length made the bundled decoder crash the whole Lambda, so the
    framing is validated here: every frame has a 2-byte length (payload only)
    followed by that many bytes, and the chain ends exactly at EOF (an optional
    final 0xFFFF sentinel is accepted). Frame count also proves duration
    without decoding.
    """
    position = 10 if data.startswith(_SILK[0]) else 9
    frames = 0
    while position < len(data):
        if position + 2 > len(data):
            raise VoiceRejected("unsupported_type")
        size = int.from_bytes(data[position:position + 2], "little")
        if size == 0xFFFF:
            # A standard SILK_V3 stream may end with a 2-byte EOF sentinel;
            # pysilk handles it, but it is only valid at exact EOF.
            if frames > 0 and position + 2 == len(data):
                position += 2
                break
            raise VoiceRejected("unsupported_type")
        next_position = position + 2 + size
        if not 1 <= size <= 1024 or next_position > len(data):
            raise VoiceRejected("unsupported_type")
        position = next_position
        frames += 1
        if frames > 6000:  # 120 s of 20 ms frames
            raise VoiceRejected("too_long")
    if frames == 0 or position != len(data):
        raise VoiceRejected("unsupported_type")


def _decode_wav(data):
    fmt, payload = _wav_chunks(data)
    audio_format, channels, rate, bits = fmt
    if audio_format != 1 or bits != 16 or rate != SAMPLE_RATE or channels not in (1, 2):
        raise VoiceRejected("unsupported_type")
    if channels == 2:
        payload = _downmix(payload)
    return _cap(payload)


def _wav_chunks(data):
    position = 12
    fmt = None
    payload = None
    while position + 8 <= len(data):
        chunk_id = data[position:position + 4]
        size = int.from_bytes(data[position + 4:position + 8], "little")
        body = data[position + 8:position + 8 + size]
        if len(body) != size:
            raise VoiceRejected("unsupported_type")
        if chunk_id == b"fmt ":
            if size < 16:
                raise VoiceRejected("unsupported_type")
            fmt = struct.unpack("<HHIIHH", body[:16])
        elif chunk_id == b"data" and payload is None:
            payload = body
        position += 8 + size + (size & 1)
    if fmt is None or payload is None:
        raise VoiceRejected("unsupported_type")
    return fmt[:2] + (fmt[2], fmt[5]), payload


def _downmix(data):
    samples = array.array("h")
    samples.frombytes(data[:len(data) - len(data) % 4])
    if sys.byteorder != "little":
        samples.byteswap()
    mono = array.array("h", (
        (samples[index] + samples[index + 1]) // 2
        for index in range(0, len(samples), 2)
    ))
    if sys.byteorder != "little":
        mono.byteswap()
    return mono.tobytes()


def _decode_ogg_opus(data):
    (channels, pre_skip), packets = _ogg_opus_packets(data)
    from opuslib_next import Decoder

    try:
        decoder = Decoder(SAMPLE_RATE, channels)
    except Exception:
        raise VoiceRejected("unsupported_type") from None
    pcm = bytearray()
    for packet in packets:
        try:
            decoded = decoder.decode(packet, _OPUS_FRAME_SAMPLES)
        except Exception:
            raise VoiceRejected("unsupported_type") from None
        if not isinstance(decoded, bytes):
            raise VoiceRejected("unsupported_type")
        if channels == 2:
            decoded = _downmix(decoded)
        pcm.extend(decoded)
        if len(pcm) > PCM_MAX_BYTES:
            raise VoiceRejected("too_long")
    # Header pre-skip padding is trimmed before the duration cap, so an exact
    # 120 s note is not tripped by its decoder lookahead frames.
    trim = pre_skip * SAMPLE_RATE // _OPUS_RATE
    if trim:
        pcm = pcm[min(len(pcm), trim * 2):]
    return _cap(bytes(pcm))


def _ogg_opus_packets(data):
    """`((channels, pre_skip), audio packets)` from one OGG/Opus stream."""
    packets = _ogg_packets(data)
    if len(packets) < 2 or len(packets[0]) < 19 or packets[0][:8] != b"OpusHead":
        raise VoiceRejected("unsupported_type")
    head = packets[0]
    channels = head[9]
    version = head[8]
    mapping_family = head[18]
    if channels not in (1, 2) or version >> 4 != 0 or mapping_family != 0:
        raise VoiceRejected("unsupported_type")
    if packets[1][:8] != b"OpusTags":
        raise VoiceRejected("unsupported_type")
    return (channels, int.from_bytes(head[10:12], "little")), packets[2:]


def _ogg_packets(data):
    position = 0
    packets = []
    partial = bytearray()
    while position < len(data):
        if position + 27 > len(data) or data[position:position + 4] != b"OggS":
            raise VoiceRejected("unsupported_type")
        if data[position + 4] != 0:
            raise VoiceRejected("unsupported_type")
        segments = data[position + 26]
        table = data[position + 27:position + 27 + segments]
        if len(table) != segments:
            raise VoiceRejected("unsupported_type")
        body = position + 27 + segments
        if body + sum(table) > len(data):
            raise VoiceRejected("unsupported_type")
        offset = body
        for seg in table:
            partial += data[offset:offset + seg]
            offset += seg
            if seg < 255:
                packets.append(bytes(partial))
                partial = bytearray()
        position = body + sum(table)
    if partial or not packets:
        raise VoiceRejected("unsupported_type")
    return packets


def _cap(pcm):
    if len(pcm) > PCM_MAX_BYTES or len(pcm) // 2 > _MAX_PCM_SAMPLES:
        raise VoiceRejected("too_long")
    return pcm


def part_offsets(pcm):
    """`(index, offset, chunk)` in <=1,000,000-byte whole-sample parts."""
    return [
        (index, offset, pcm[offset:offset + _PART_BYTES])
        for index, offset in enumerate(range(0, len(pcm), _PART_BYTES))
    ]
