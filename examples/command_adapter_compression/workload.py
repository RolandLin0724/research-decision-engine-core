"""Direct-child workload for the CommandAdapter compression example."""

from __future__ import annotations

import argparse
import bz2
import gzip
import json
import lzma
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from examples.command_adapter_compression.corpus_data import load_corpus
else:
    if __package__:
        from .corpus_data import load_corpus
    else:
        from corpus_data import load_corpus

CODECS = ("gzip", "bz2", "lzma")
LEVELS = (1, 3, 6, 9)
CHUNK_MODES = ("single_stream", "fixed_64_kib_members")
CHUNK_BYTES = 64 * 1024
_CODEC_WORK_WEIGHTS = {"gzip": 1, "bz2": 3, "lzma": 5}
_LZMA_DICTIONARY_BYTES = {1: 64 * 1024, 3: 256 * 1024, 6: 1024 * 1024, 9: 4 * 1024 * 1024}
_LZMA_NICE_LENGTH = {1: 32, 3: 64, 6: 128, 9: 192}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codec", choices=CODECS, required=True)
    parser.add_argument("--level", choices=LEVELS, type=int, required=True)
    parser.add_argument("--chunk-mode", choices=CHUNK_MODES, required=True)
    parser.add_argument("--counter-file", type=Path, required=True)
    return parser


def _compress_member(payload: bytes, *, codec: str, level: int) -> bytes:
    if codec == "gzip":
        return gzip.compress(payload, compresslevel=level, mtime=0)
    if codec == "bz2":
        return bz2.compress(payload, compresslevel=level)
    filters = [
        {
            "id": lzma.FILTER_LZMA2,
            "dict_size": _LZMA_DICTIONARY_BYTES[level],
            "lc": 3,
            "lp": 0,
            "pb": 2,
            "mode": lzma.MODE_NORMAL,
            "nice_len": _LZMA_NICE_LENGTH[level],
            "mf": lzma.MF_BT4,
            "depth": 0,
        }
    ]
    return lzma.compress(payload, format=lzma.FORMAT_XZ, filters=filters)


def _compress(payload: bytes, *, codec: str, level: int, chunk_mode: str) -> tuple[bytes, int]:
    members = (
        (payload,)
        if chunk_mode == "single_stream"
        else tuple(
            payload[offset : offset + CHUNK_BYTES] for offset in range(0, len(payload), CHUNK_BYTES)
        )
    )
    return b"".join(_compress_member(member, codec=codec, level=level) for member in members), len(
        members
    )


def _decompress(payload: bytes, *, codec: str) -> bytes:
    if codec == "gzip":
        return gzip.decompress(payload)
    if codec == "bz2":
        return bz2.decompress(payload)
    return lzma.decompress(payload, format=lzma.FORMAT_AUTO)


def _increment_counter(path: Path) -> int:
    if path.exists():
        text = path.read_text(encoding="ascii")
        if not text.endswith("\n") or not text[:-1].isdigit():
            raise RuntimeError("Command counter is malformed.")
        count = int(text[:-1])
    else:
        count = 0
    path.write_text(f"{count + 1}\n", encoding="ascii", newline="\n")
    return count + 1


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    corpus = load_corpus()
    invocation_count = _increment_counter(args.counter_file)
    compressed, member_count = _compress(
        corpus,
        codec=args.codec,
        level=args.level,
        chunk_mode=args.chunk_mode,
    )
    if _decompress(compressed, codec=args.codec) != corpus:
        raise RuntimeError("Compression round trip changed corpus bytes.")

    compression_ratio = len(corpus) / len(compressed)
    weighted_byte_work = (
        len(corpus) * _CODEC_WORK_WEIGHTS[args.codec] * (args.level + 1)
        + member_count * CHUNK_BYTES
    )
    observation = {
        "cost": weighted_byte_work / 1_000_000.0,
        "objective_value": compression_ratio,
    }
    encoded = (
        json.dumps(
            observation,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    print(
        f"invocation={invocation_count} codec={args.codec} level={args.level} "
        f"chunk_mode={args.chunk_mode} members={member_count} compressed_bytes={len(compressed)}",
        file=sys.stderr,
    )
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
