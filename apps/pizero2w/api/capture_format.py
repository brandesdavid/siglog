import os

CAPTURE_SAMPLE_RATE = int(os.getenv("SIGLOG_CAPTURE_RATE", "140000"))
CAPTURE_BYTES_PER_SEC = CAPTURE_SAMPLE_RATE * 4


def rtl_fm_lrpt_cmd(freq_mhz: float, duration_sec: int, wav_path: str) -> list[str]:
    return [
        "timeout",
        str(duration_sec),
        "rtl_fm",
        "-d",
        "0",
        "-f",
        f"{freq_mhz}M",
        "-M",
        "raw",
        "-s",
        str(CAPTURE_SAMPLE_RATE),
        "-g",
        "40",
        "-E",
        "dc",
        "-E",
        "wav",
        str(wav_path),
    ]


def satdump_decode_hint(freq_mhz: float) -> str:
    rate = CAPTURE_SAMPLE_RATE
    sat = "M2-4" if freq_mhz >= 137.5 else "M2"
    return (
        f"SatDump: meteor_m2-x_lrpt · baseband · {rate} Hz · s16 · {sat} "
        f"(or meteor_m2_lrpt if {rate} Hz fails)"
    )
