"""SAS character functions."""

from __future__ import annotations

import math
import re
from typing import Any


def substr(s: Any, start: int, length: int | None = None) -> str:
    """SUBSTR(string, start [, length]) — extract or replace substring."""
    s = _to_str(s)
    start = int(start) - 1  # SAS is 1-indexed
    if start < 0:
        start = 0
    if length is None:
        return s[start:]
    return s[start : start + int(length)]


def scan(s: Any, n: int, delimiters: str = " \t\n\r\f.-/,;:!?()[]{}") -> str:
    """SCAN(string, n [, delimiters]) — extract nth word.
    Default delimiters: space, tab, newline, and common punctuation."""
    s = _to_str(s)
    if not delimiters:
        delimiters = " \t\n\r\f.-/,;:!?()[]{}"
    # SAS SCAN treats consecutive delimiters as one
    pattern = f"[{re.escape(delimiters)}]+"
    parts = re.split(pattern, s.strip())
    parts = [p for p in parts if p]
    idx = int(n) - 1
    if 0 <= idx < len(parts):
        return parts[idx]
    return ""


def compress(s: Any, chars: str = "", modifiers: str = "") -> str:
    """COMPRESS(string [, chars [, modifiers]]) — remove/keep characters."""
    s = _to_str(s)
    if not chars:
        # Default: remove blanks
        return s.replace(" ", "")

    mod = modifiers.upper() if modifiers else ""
    if "K" in mod:
        # Keep mode: keep only specified chars
        result = "".join(c for c in s if c in chars)
    else:
        # Remove mode: remove specified chars
        result = s
        for c in chars:
            result = result.replace(c, "")

    if "L" in mod:
        result = result.lower()
    elif "U" in mod:
        result = result.upper()
    return result


def upcase(s: Any) -> str:
    """UPCASE(string) — convert to uppercase."""
    return _to_str(s).upper()


def lowcase(s: Any) -> str:
    """LOWCASE(string) — convert to lowercase."""
    return _to_str(s).lower()


def strip(s: Any) -> str:
    """STRIP(string) — remove leading and trailing blanks."""
    return _to_str(s).strip()


def trim(s: Any) -> str:
    """TRIM(string) — remove trailing blanks."""
    return _to_str(s).rstrip()


def left(s: Any) -> str:
    """LEFT(string) — left-justify (remove leading blanks)."""
    return _to_str(s).lstrip()


def cat(*args: Any) -> str:
    """CAT(s1, s2, ...) — concatenate without trimming."""
    return "".join(str(a) if a is not None else "" for a in args)


def cats(*args: Any) -> str:
    """CATS(s1, s2, ...) — concatenate with strip."""
    return "".join(_to_str(a).strip() for a in args)


def catx(sep: str, *args: Any) -> str:
    """CATX(sep, s1, s2, ...) — concatenate with separator and strip.
    Skips blank values and SAS missing values ('.')."""
    from saslite.runtime.types import is_missing
    parts = []
    for a in args:
        if is_missing(a):
            continue
        s = _to_str(a).strip()
        if s and s != ".":
            parts.append(s)
    return sep.join(parts)


def compbl(s: Any) -> str:
    """COMPBL(string) — compress multiple blanks to single."""
    return re.sub(r"\s+", " ", _to_str(s))


def tranwrd(s: Any, find: str, replace: str) -> str:
    """TRANWRD(string, find, replace) — replace all occurrences."""
    return _to_str(s).replace(find, replace)


def index(s: Any, substring: str) -> int:
    """INDEX(string, substring) — find position (0 if not found)."""
    pos = _to_str(s).find(substring)
    return pos + 1 if pos >= 0 else 0


def find(s: Any, substring: Any, modifiers_or_start: Any = "", start_pos: Any = 1) -> int:
    """FIND(string, substring [, modifiers [, start]]) — enhanced find.
    If third argument is numeric, treat it as start position."""
    haystack = _to_str(s)
    needle = _to_str(substring)

    # Determine if third argument is modifiers or start position
    if isinstance(modifiers_or_start, (int, float)):
        # Third argument is start position
        start_idx = int(modifiers_or_start) - 1
        mod_str = ""
    else:
        # Third argument is modifiers
        mod_str = _to_str(modifiers_or_start) if modifiers_or_start else ""
        start_idx = int(start_pos) - 1 if isinstance(start_pos, (int, float)) else 0

    if start_idx < 0:
        start_idx = 0

    if "I" in mod_str.upper():
        haystack = haystack.lower()
        needle = needle.lower()

    pos = haystack.find(needle, start_idx)
    return pos + 1 if pos >= 0 else 0


def count(s: Any, substring: str) -> int:
    """COUNT(string, substring) — count occurrences."""
    return _to_str(s).count(substring)


def repeat(s: Any, n: int) -> str:
    """REPEAT(string, n) — repeat n times."""
    return _to_str(s) * int(n)


def reverse(s: Any) -> str:
    """REVERSE(string) — reverse characters."""
    return _to_str(s)[::-1]


def length(s: Any) -> int:
    """LENGTH(string) — length after removing trailing blanks.
    Returns 1 for strings that are all blanks (SAS behavior)."""
    text = _to_str(s)
    trimmed = text.rstrip()
    # SAS returns 1 for all-blank strings
    if not trimmed and text:
        return 1
    return len(trimmed)


def lengthc(s: Any) -> int:
    """LENGTHC(string) — length including trailing blanks."""
    return len(_to_str(s))


def missing(s: Any) -> int:
    """MISSING(var) — test for missing (1=missing, 0=not)."""
    if s is None:
        return 1
    if isinstance(s, str) and s == "":
        return 1
    if isinstance(s, float) and math.isnan(s):
        return 1
    return 0


def coalescec(*args: Any) -> Any:
    """COALESCEC(s1, s2, ...) — first non-missing character."""
    from saslite.runtime.types import is_missing
    for a in args:
        if not is_missing(a):
            s = str(a)
            if s != "":  # SAS: empty string is missing for char variables
                return s
    try:
        import pandas as pd
        return pd.NA
    except ImportError:
        return float("nan")


def like_match(source: Any, pattern: Any) -> bool:
    """LIKE(source, pattern) — match SQL/SAS LIKE wildcards."""
    if source is None or pattern is None:
        return False
    if isinstance(source, float) and math.isnan(source):
        return False
    if isinstance(pattern, float) and math.isnan(pattern):
        return False
    return re.match(_like_pattern_to_regex(_to_str(pattern)), _to_str(source)) is not None


def _like_pattern_to_regex(pattern: str) -> str:
    """Convert a LIKE pattern into an anchored regex."""
    pieces: list[str] = ["^"]
    for char in pattern:
        if char == "%":
            pieces.append(".*")
        elif char == "_":
            pieces.append(".")
        else:
            pieces.append(re.escape(char))
    pieces.append("$")
    return "".join(pieces)


def _to_str(s: Any) -> str:
    from saslite.runtime.types import is_missing
    if is_missing(s):
        return "."
    return str(s)


def prxmatch(pattern: Any, source: Any) -> int:
    """PRXMATCH('/regex/', string) — Perl regex match, returns position (0=not found)."""
    p = _to_str(pattern).strip()
    s = _to_str(source)
    # Strip surrounding quotes if present
    if len(p) >= 2 and p[0] == '/' and '/' in p[1:]:
        # Extract regex from /pattern/flags
        end = p.rindex('/')
        regex = p[1:end]
        flags_str = p[end+1:]
        re_flags = 0
        if 'i' in flags_str:
            re_flags |= re.IGNORECASE
        try:
            m = re.search(regex, s, re_flags)
            return m.start() + 1 if m else 0
        except re.error:
            return 0
    else:
        # Treat as bare regex pattern
        try:
            m = re.search(p, s)
            return m.start() + 1 if m else 0
        except re.error:
            return 0


def prxchange(pattern: Any, times: Any, source: Any) -> str:
    """PRXCHANGE substitution using a SAS Perl-regex expression.

    ``times`` is the maximum number of substitutions; a negative value means
    replace every match.  SAS replacement backreferences such as ``$1`` and
    ``${1}`` are translated to their Python equivalents.
    """
    text = _to_str(source)
    parsed = _parse_prx_substitution(_to_str(pattern).strip())
    if parsed is None:
        return text

    regex, replacement, flags = parsed
    try:
        limit = int(float(times))
    except (TypeError, ValueError, OverflowError):
        return text
    if limit == 0:
        return text

    count = 0 if limit < 0 else limit
    try:
        compiled = re.compile(regex, flags)
        python_replacement = _translate_prx_replacement(replacement)
        return compiled.sub(python_replacement, text, count=count)
    except (re.error, IndexError):
        # Match PRXMATCH's compatibility behavior: an invalid PRX expression
        # does not abort the surrounding DATA step.
        return text


def _parse_prx_substitution(
    expression: str,
) -> tuple[str, str, int] | None:
    """Parse ``s/pattern/replacement/flags`` with any SAS PRX delimiter."""
    if len(expression) < 4 or expression[0].lower() != "s":
        return None
    delimiter = expression[1]
    if delimiter.isalnum() or delimiter.isspace() or delimiter == "\\":
        return None

    pattern, position = _read_prx_part(expression, 2, delimiter)
    if pattern is None:
        return None
    replacement, position = _read_prx_part(expression, position, delimiter)
    if replacement is None:
        return None

    modifiers = expression[position:].strip().lower()
    if any(modifier not in "imsxo" for modifier in modifiers):
        return None
    flags = 0
    if "i" in modifiers:
        flags |= re.IGNORECASE
    if "m" in modifiers:
        flags |= re.MULTILINE
    if "s" in modifiers:
        flags |= re.DOTALL
    if "x" in modifiers:
        flags |= re.VERBOSE
    # The SAS/Perl ``o`` modifier compiles the expression once. Python already
    # caches compiled regular expressions, so it needs no separate handling.
    return pattern, replacement, flags


def _read_prx_part(
    expression: str, position: int, delimiter: str
) -> tuple[str | None, int]:
    """Read one delimiter-terminated PRX part, preserving regex escapes."""
    chars: list[str] = []
    while position < len(expression):
        char = expression[position]
        if char == delimiter:
            return "".join(chars), position + 1
        if char == "\\" and position + 1 < len(expression):
            next_char = expression[position + 1]
            if next_char == delimiter:
                chars.append(delimiter)
            else:
                chars.extend((char, next_char))
            position += 2
            continue
        chars.append(char)
        position += 1
    return None, position


def _translate_prx_replacement(replacement: str) -> str:
    """Translate Perl/SAS dollar backreferences for :func:`re.sub`."""
    translated = re.sub(r"\$\{(\d+)\}", r"\\g<\1>", replacement)
    translated = re.sub(r"\$(\d+)", r"\\g<\1>", translated)
    return translated.replace("$&", r"\g<0>")


def propcase(s: Any, delimiters: str = " /-") -> str:
    """PROPCASE(string [, delimiters]) — convert to proper case (title case)."""
    text = _to_str(s)
    if not text:
        return text

    # Split by delimiters and capitalize first letter of each word
    result = []
    current_word = []

    for char in text:
        if char in delimiters:
            if current_word:
                word = ''.join(current_word)
                result.append(word[0].upper() + word[1:].lower() if word else '')
                current_word = []
            result.append(char)
        else:
            current_word.append(char)

    # Handle last word
    if current_word:
        word = ''.join(current_word)
        result.append(word[0].upper() + word[1:].lower() if word else '')

    return ''.join(result)


def countw(s: Any, delimiters: str = " \t\n") -> int:
    """COUNTW(string [, delimiters]) — count words."""
    text = _to_str(s)
    if not text:
        return 0

    # Split by delimiters and count non-empty parts
    pattern = f"[{re.escape(delimiters)}]+"
    parts = re.split(pattern, text.strip())
    return len([p for p in parts if p])


def verify(s: Any, charset: str, modifiers: str = "") -> int:
    """VERIFY(string, charset [, modifiers]) — find first char not in charset.
    Returns position (1-based) of first character not in charset, or 0 if all match."""
    text = _to_str(s)
    charset_str = _to_str(charset)

    for i, char in enumerate(text):
        if char not in charset_str:
            return i + 1
    return 0


def substrn(s: Any, start: int, length: int | None = None) -> str:
    """SUBSTRN(string, start [, length]) — same as SUBSTR but handles missing differently."""
    return substr(s, start, length)


def translate(s: Any, to_chars: str, from_chars: str) -> str:
    """TRANSLATE(string, to, from) — character-by-character replacement."""
    text = _to_str(s)
    to_str = _to_str(to_chars)
    from_str = _to_str(from_chars)

    # Build translation table
    trans_table = str.maketrans(from_str, to_str)
    return text.translate(trans_table)


def rank_char(s: Any) -> float:
    """RANK(char) — ASCII code of the first character."""
    text = _to_str(s)
    if not text:
        return float("nan")
    return float(ord(text[0]))


def byte(n: Any) -> str:
    """BYTE(n) — character for ASCII code n."""
    try:
        code = int(float(n))
    except (TypeError, ValueError):
        return ""
    if 0 <= code < 256:
        return chr(code)
    return ""
