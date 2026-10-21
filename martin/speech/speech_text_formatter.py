"""Převod Markdown odpovědi na přirozenou mluvenou češtinu.

Modul odděluje to, co Martin *zobrazí* (Markdown, jak to napsal model)
od toho, co Martin *řekne* (čistá, přirozená mluvenina).

Pravidla:
  * Markdown značky se NIKDY nečtou nahlas.
  * Zachovává se přirozená interpunkce, čísla, česká diakritika.
  * Odkazy se čtou jako jejich text, ne jako URL.
  * Bloky kódu se přečtou stručně, ne symbolicky.
  * Tabulky se čtou jako řádky "sloupec: hodnota".
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

__all__ = [
    "to_speech_text",
    "strip_code_blocks",
    "strip_inline_code",
    "strip_links",
    "strip_tables",
    "strip_headings",
    "strip_list_markers",
    "strip_emphasis",
    "strip_blockquotes",
    "strip_horizontal_rules",
    "normalize_whitespace",
    "describe_code_block",
    "MAX_SPEECH_CHARS",
]

# Delka, po kterou se reč zkrátí (nastavení `speak_summaries`).
MAX_SPEECH_CHARS = 400

# URL, ktere nechame cist jako text (napr. "martin.ai").
_FRIENDLY_HOSTS = ("martin.ai",)


# ---------------------------------------------------------------------------
# Bloky kodu
# ---------------------------------------------------------------------------
_CODE_BLOCK = re.compile(r"```[^\n]*\n(.*?)(?:```|$)", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")


def describe_code_block(code: str) -> str:
    """Popise blok kodu tak, aby to znelo prirozene a strucne.

    "`def foo(): pass`" -> "blok kódu se třemi řádky"
    """
    lines = [line for line in code.splitlines() if line.strip()]
    if not lines:
        return "prázdný blok kódu"
    count = len(lines)
    if count == 1:
        return "blok kódu s jedním řádkem"
    return f"blok kódu s {count} řádky"


def strip_code_blocks(text: str) -> str:
    """Nahradí blokové kódy popiskem."""
    if not text:
        return ""
    return _CODE_BLOCK.sub(lambda m: describe_code_block(m.group(1)), text)


def strip_inline_code(text: str) -> str:
    """Odstraní_inline_ značky, obsah ponechá."""
    if not text:
        return ""
    return _INLINE_CODE.sub(lambda m: m.group(1), text)


# ---------------------------------------------------------------------------
# Odkazy
# ---------------------------------------------------------------------------
_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_AUTOLINK = re.compile(r"<((?:https?|ftp)://[^>\s]+)>")
_BARE_URL = re.compile(r"\b(?:https?|ftp)://[^\s<>\"')]+")


def _url_to_speech(url: str) -> str:
    """Převede URL na přirozenou mluvenou podobu."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return "odkaz"
    host = (parsed.netloc or "").lower()
    # Odstranit pridanych uzivatelskych udaju z hostu.
    host = host.split("@")[-1]
    if not host:
        return "odkaz"
    if host in _FRIENDLY_HOSTS:
        return host
    # "https://example.com/docs" -> "odkaz na example.com"
    # Host bez "www." znel prirozeneji.
    spoken = host[4:] if host.startswith("www.") else host
    return f"odkaz na {spoken}"


def strip_links(text: str) -> str:
    """Odkazy nahradi jejich textem (nebo prirozonym popiskem)."""
    if not text:
        return ""
    text = _LINK.sub(lambda m: m.group(1).strip() or _url_to_speech(m.group(2)), text)
    text = _AUTOLINK.sub(lambda m: _url_to_speech(m.group(1)), text)
    text = _BARE_URL.sub(lambda m: _url_to_speech(m.group(0)), text)
    return text


# ---------------------------------------------------------------------------
# Tabulky
# ---------------------------------------------------------------------------
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEP = re.compile(r"^\s*\|[\s:|-]+\|\s*$")


def strip_tables(text: str) -> str:
    """Tabulku prevede na radky "Nazev: hodnota".

    "| A | B |" + "|---|---|" + "| 1 | 2 |"  ->  "A: 1, B: 2"
    """
    if not text or "|" not in text:
        return text
    lines = text.splitlines()
    out: list[str] = []
    header: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if _TABLE_ROW.match(line) and index + 1 < len(lines) and _TABLE_SEP.match(
            lines[index + 1]
        ):
            header = _split_row(line)
            index += 2
            while index < len(lines) and _TABLE_ROW.match(lines[index]):
                cells = _split_row(lines[index])
                parts = []
                for position, cell in enumerate(cells):
                    if not cell:
                        continue
                    label = header[position] if position < len(header) else ""
                    parts.append(f"{label}: {cell}" if label else cell)
                if parts:
                    out.append(", ".join(parts))
                index += 1
            out.append("")  # oddeleni tabulky od okolniho textu
            continue
        out.append(line)
        index += 1
    return "\n".join(out)


def _split_row(line: str) -> list[str]:
    """Rozdeli radek tabulky na bunky."""
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


# ---------------------------------------------------------------------------
# Nadpisy, seznamy, ostatni Markdown
# ---------------------------------------------------------------------------
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_SETEXT = re.compile(r"^\s*(=+|-{2,})\s*$", re.MULTILINE)
_LIST_MARKER = re.compile(r"^\s*([*+-]|\d+[.)])\s+", re.MULTILINE)
_TASK_MARKER = re.compile(r"^\s*[-*+]\s+\[[ xX]\]\s*", re.MULTILINE)
_BLOCKQUOTE = re.compile(r"^\s*>\s?", re.MULTILINE)
_HR = re.compile(r"^\s*([-*_])\s*(?:\1\s*){2,}$", re.MULTILINE)
_EMPHASIS = re.compile(r"(\*\*\*|\*\*|\*|___|__|_)(?=\S)(.+?)(?<=\S)\1", re.DOTALL)
_STRIKE = re.compile(r"~~(.+?)~~", re.DOTALL)
_HTML_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
_FOOTNOTE = re.compile(r"\[\^[^\]]+\]")


def strip_headings(text: str) -> str:
    """Odstrani značky nadpisu."""
    if not text:
        return ""
    return _HEADING.sub("", text)


def strip_list_markers(text: str) -> str:
    """Odstrani odrážky a číslování seznamů.

    "- Otevři aplikaci" -> "Otevři aplikaci"
    "1. Otevři" -> "Otevři"
    """
    if not text:
        return ""
    text = _TASK_MARKER.sub("", text)
    return _LIST_MARKER.sub("", text)


def strip_emphasis(text: str) -> str:
    """Odstrani tucne/kurzyve zvyrazneni."""
    if not text:
        return ""
    # Nejdrive dvojnasobne, pak jednoduche - jinak by se rozpadlo.
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"__(.+?)__", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"__(.+?)__", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"\*(.+?)\*", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"(?<![\w_])_(.+?)_(?![\w_])", r"\1", text, flags=re.DOTALL)
    text = _STRIKE.sub(r"\1", text)
    return text


def strip_blockquotes(text: str) -> str:
    """Odstrani značky citace."""
    if not text:
        return ""
    return _BLOCKQUOTE.sub("", text)


def strip_horizontal_rules(text: str) -> str:
    """Odstrani vodorovne cary."""
    if not text:
        return ""
    return _HR.sub("", text)


def _strip_html(text: str) -> str:
    if not text:
        return ""
    return _HTML_TAG.sub("", text)


# ---------------------------------------------------------------------------
# Normalizace
# ---------------------------------------------------------------------------
_MULTI_NEWLINE = re.compile(r"\n{3,}")
_SPACES = re.compile(r"[ \t]{2,}")


def normalize_whitespace(text: str) -> str:
    """Sjednoti bile znaky a prazdne radky."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _SPACES.sub(" ", text)
    text = _MULTI_NEWLINE.sub("\n\n", text)
    # Prazdne radky vysledkem listu - smaz.
    text = re.sub(r"^\s*[-*+]\s*$", "", text, flags=re.MULTILINE)
    return text.strip()


# Tokeny, u kterych se nesmi sahat na interpunkci:
#   - domeny:  "martin.ai", "example.com"
#   - desetinna cisla: "12.50"
#   - zkratky s teckou: "napr."
_PROTECTED = re.compile(
    r"\b[\w-]+\.[a-zA-Z]{2,}\b|\b\d+[.,]\d+\b|\b(?:napr|tzn|resp|atd|poč|c|str|odp|max|min|mgr|ing|jr|sr)\.",
    re.IGNORECASE,
)
_PLACEHOLDER = "\x00PROTECTED%d\x00"


def _fix_punctuation(text: str) -> str:
    """Srovna interpunkci tak, aby to znelo prirozene.

    Domeny, desetinna cisla a zkratky se docasne schovaji, aby se
    v nich nerozdelila tecka (napr. "martin.ai" nesmi znic "martin. ai").
    """
    if not text:
        return ""
    protected: list[str] = []

    def stash(match: re.Match[str]) -> str:
        protected.append(match.group(0))
        return _PLACEHOLDER % (len(protected) - 1)

    text = _PROTECTED.sub(stash, text)
    # "...text" -> "... text" (chybějici mezera za interpunkci)
    text = re.sub(r"([.,!?;:])([^\s\d.,!?;:])", r"\1 \2", text)
    # Mezera pred interpunkci.
    text = re.sub(r"\s+([.,!?;:])", r"\1", text)
    # Dvojte mezery.
    text = re.sub(r"[ \t]{2,}", " ", text)

    for index, value in enumerate(protected):
        text = text.replace(_PLACEHOLDER % index, value)
    return text


def _strip_residual_markup(text: str) -> str:
    """Odstrani zbylé Markdown značky, ktere by se jinak cetly nahlas."""
    if not text:
        return ""
    text = _FOOTNOTE.sub("", text)
    text = re.sub(r"\\([*_`~\[\]#|])", r"\1", text)  # escapovane znaky
    text = text.replace("**", "").replace("__", "")
    text = re.sub(r"(?<![\w*])\*(?!\s)", "", text)
    text = re.sub(r"(?<!\s)\*(?![\w*])", "", text)
    text = text.replace("`", "")
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*>\s?", "", text, flags=re.MULTILINE)
    return text


def to_speech_text(
    markdown: str,
    max_chars: int = MAX_SPEECH_CHARS,
    keep_trailing_space: bool = False,
) -> str:
    """Prevede Markdown odpoved na text pro mluveni.

    Výstup je vždy bezpečný k přečtení - neobsahuje zádné Markdown
    značky, ale zachovává přirozenou strukturu a interpunkci.

    `keep_trailing_space` je potřeba při streamingu - mezi dvěma
    chunky textu nesmí zmizet mezera, jinak se slova slepí
    ("spustimMicrosoft").
    """
    if not markdown or not markdown.strip():
        return ""
    trailing = " " if (keep_trailing_space and markdown.endswith(" ")) else ""

    text = markdown
    text = strip_code_blocks(text)
    text = strip_tables(text)
    text = strip_links(text)
    text = strip_inline_code(text)
    text = strip_headings(text)
    text = strip_list_markers(text)
    text = strip_blockquotes(text)
    text = strip_horizontal_rules(text)
    text = strip_emphasis(text)
    text = _strip_html(text)
    text = _strip_residual_markup(text)
    text = normalize_whitespace(text)
    text = _fix_punctuation(text)

    # Kazde vetev na vlastni radku se cte jako samostatna veta.
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    text = " ".join(lines)

    if max_chars and len(text) > max_chars:
        text = _truncate(text, max_chars)
    result = text.strip()
    if trailing and result:
        result += trailing
    return result


def _truncate(text: str, max_chars: int) -> str:
    """Zkrati text na prirozene mezi větami."""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    for marker in (". ", "! ", "? "):
        index = cut.rfind(marker)
        if index > max_chars * 0.4:
            return cut[: index + 1].strip()
    # Bez vety - zkrat na slovni mezi.
    index = cut.rfind(" ")
    if index > max_chars * 0.5:
        return cut[:index].rstrip() + "..."
    return cut.rstrip() + "..."
