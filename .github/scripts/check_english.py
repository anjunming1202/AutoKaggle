"""Fail when tracked text files, or text on stdin, contain letters from non-English scripts.

The repository is written in English. Latin letters (including accented ones),
Greek letters and letter-like symbols used in formulas, digits, punctuation and
other symbols are allowed. A test that needs another script can write it as an
escape such as "\\u4e2d".

Usage:
  python3 .github/scripts/check_english.py               check every tracked file
  python3 .github/scripts/check_english.py --stdin NAME  check text read from stdin
"""
import subprocess
import sys
import unicodedata

ALLOWED_PREFIXES = ("LATIN", "GREEK", "MODIFIER LETTER")
ALLOWED_NAMES = {"MICRO SIGN", "FEMININE ORDINAL INDICATOR", "MASCULINE ORDINAL INDICATOR"}


def allowed(char):
    if char.isascii() or not unicodedata.category(char).startswith("L"):
        return True
    name = unicodedata.name(char, "")
    # U+2100 to U+214F are letter-like symbols such as the script l in formulas.
    return name.startswith(ALLOWED_PREFIXES) or name in ALLOWED_NAMES or 0x2100 <= ord(char) <= 0x214F


def report(source, text):
    found = [(number, column, char) for number, line in enumerate(text.splitlines(), 1)
             for column, char in enumerate(line, 1) if not allowed(char)]
    for number, column, char in found[:20]:
        print(f"{source}:{number}:{column}: {unicodedata.name(char, hex(ord(char)))}")
    if len(found) > 20:
        print(f"{source}: {len(found) - 20} more")
    return bool(found)


def tracked_files():
    listing = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True).stdout
    for path in listing.decode("utf-8").split("\0"):
        if not path:
            continue
        try:
            with open(path, "rb") as handle:
                data = handle.read()
        except OSError:
            continue
        if b"\0" in data:
            continue
        try:
            yield path, data.decode("utf-8")
        except UnicodeDecodeError:
            continue


def main():
    if sys.argv[1:2] == ["--stdin"]:
        text = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        failed = report(sys.argv[2] if len(sys.argv) > 2 else "stdin", text)
    else:
        failed = False
        for path, text in tracked_files():
            failed = report(path, text) or failed
    if failed:
        print("Use English. Write other scripts as escapes, for example \\u4e2d, when a test needs them.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
