"""Audio conversion between a phone line and Gemini Live.

Twilio Media Streams carry 8 kHz G.711 μ-law (one byte per sample). Gemini Live takes 16 kHz 16-bit PCM and
answers with 24 kHz 16-bit PCM. Python's audioop module (which did this) was removed in Python 3.13, so this is a
small pure-Python version with lookup tables. Phone audio is only 8000 samples a second, so it's fast enough.
"""

import array
import sys

_BIAS = 0x84
_CLIP = 32635


def _decode_byte(u: int) -> int:
    u = ~u & 0xFF
    sign, exponent, mantissa = u & 0x80, (u >> 4) & 0x07, u & 0x0F
    sample = (((mantissa << 3) + _BIAS) << exponent) - _BIAS
    return -sample if sign else sample


def _encode_sample(sample: int) -> int:
    sign = 0x80 if sample < 0 else 0
    sample = min(abs(sample), _CLIP) + _BIAS
    exponent = 7
    mask = 0x4000
    while exponent > 0 and not sample & mask:
        exponent -= 1
        mask >>= 1
    mantissa = (sample >> (exponent + 3)) & 0x0F
    return ~(sign | (exponent << 4) | mantissa) & 0xFF


_DECODE = [_decode_byte(u) for u in range(256)]
# Encoding table indexed by the sample's top 14 bits (enough precision for μ-law).
_ENCODE = bytes(_encode_sample((i << 2) - 32768) for i in range(16384))


def _pcm16(data: bytes) -> array.array:
    samples = array.array("h")
    samples.frombytes(data[: len(data) // 2 * 2])
    if sys.byteorder == "big":
        samples.byteswap()
    return samples


def _bytes(samples: array.array) -> bytes:
    if sys.byteorder == "big":
        samples.byteswap()
    return samples.tobytes()


def ulaw_to_pcm16k(ulaw: bytes) -> bytes:
    """Phone audio (8 kHz μ-law) → Gemini input (16 kHz 16-bit PCM), with linear interpolation."""
    pcm8 = [_DECODE[b] for b in ulaw]
    out = array.array("h", bytes(len(pcm8) * 4))
    for i, sample in enumerate(pcm8):
        following = pcm8[i + 1] if i + 1 < len(pcm8) else sample
        out[2 * i] = sample
        out[2 * i + 1] = (sample + following) // 2
    return _bytes(out)


def pcm24k_to_ulaw(pcm: bytes) -> bytes:
    """Gemini output (24 kHz 16-bit PCM) → phone audio (8 kHz μ-law). Averaging each 3 samples is a simple
    low-pass filter, so the downsampling doesn't alias."""
    samples = _pcm16(pcm)
    n = len(samples) // 3
    return bytes(
        _ENCODE[((samples[3 * i] + samples[3 * i + 1] + samples[3 * i + 2]) // 3 + 32768) >> 2] for i in range(n)
    )
