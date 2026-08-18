#!/usr/bin/env python3
"""Minimal MPQ v1 writer used by the canonical Adventurer client patch builder.

This module only knows how to pack a mapping of archive paths to bytes. It does
not know about SpellDraft gameplay data, Adventurer DBC semantics, or patch
names. Keeping the archive writer isolated lets the official client patch
builder remain small and self-contained.
"""

import struct


def _build_crypt_table():
    table = [0] * 0x500
    seed = 0x00100001
    for index1 in range(0x100):
        index2 = index1
        for _ in range(5):
            seed = (seed * 125 + 3) % 0x2AAAAB
            temp1 = (seed & 0xFFFF) << 0x10
            seed = (seed * 125 + 3) % 0x2AAAAB
            temp2 = seed & 0xFFFF
            table[index2] = temp1 | temp2
            index2 += 0x100
    return table


_CRYPT = _build_crypt_table()


def _hash_string(value, hash_type):
    seed1, seed2 = 0x7FED7FED, 0xEEEEEEEE
    for ch in value.upper():
        crypt_value = _CRYPT[(hash_type << 8) + ord(ch)]
        seed1 = (crypt_value ^ ((seed1 + seed2) & 0xFFFFFFFF)) & 0xFFFFFFFF
        seed2 = (ord(ch) + seed1 + seed2 + (seed2 << 5) + 3) & 0xFFFFFFFF
    return seed1


def _encrypt(words, key):
    seed = 0xEEEEEEEE
    out = []
    for word in words:
        seed = (seed + _CRYPT[0x400 + (key & 0xFF)]) & 0xFFFFFFFF
        out.append(word ^ ((key + seed) & 0xFFFFFFFF))
        key = (((~key << 0x15) + 0x11111111) | (key >> 0x0B)) & 0xFFFFFFFF
        seed = (word + seed + (seed << 5) + 3) & 0xFFFFFFFF
    return out


def write_mpq(dest, files):
    """Write an MPQ v1 archive from {archive_path: bytes}."""
    files = dict(files)
    files["(listfile)"] = ("\r\n".join(files) + "\r\n").encode()

    hash_size = 1
    while hash_size < len(files) * 2:
        hash_size *= 2

    header_size = 32
    blobs = []
    block_entries = []
    offset = header_size
    hash_entries = [
        [0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF]
        for _ in range(hash_size)
    ]

    for block_index, (name, data) in enumerate(files.items()):
        blobs.append(data)
        # Store raw multi-sector files. Do not use SINGLE_UNIT: WoW 3.3.5's
        # async reader can corrupt the heap when streaming those archives.
        block_entries.append((offset, len(data), len(data), 0x80000000))
        idx = _hash_string(name, 0) & (hash_size - 1)
        while hash_entries[idx][3] != 0xFFFFFFFF:
            idx = (idx + 1) & (hash_size - 1)
        hash_entries[idx] = [
            _hash_string(name, 1),
            _hash_string(name, 2),
            0,
            block_index,
        ]
        offset += len(data)

    hash_words = []
    for entry in hash_entries:
        hash_words += entry

    block_words = []
    for entry in block_entries:
        block_words += list(entry)

    hash_data = struct.pack(
        f"<{len(hash_words)}I",
        *_encrypt(hash_words, _hash_string("(hash table)", 3)),
    )
    block_data = struct.pack(
        f"<{len(block_words)}I",
        *_encrypt(block_words, _hash_string("(block table)", 3)),
    )

    hash_pos = offset
    block_pos = hash_pos + len(hash_data)
    archive_size = block_pos + len(block_data)

    header = struct.pack(
        "<4sIIHHIIII",
        b"MPQ\x1a",
        header_size,
        archive_size,
        0,
        3,
        hash_pos,
        block_pos,
        hash_size,
        len(block_entries),
    )

    with open(dest, "wb") as handle:
        handle.write(header)
        for blob in blobs:
            handle.write(blob)
        handle.write(hash_data)
        handle.write(block_data)
