"""Testy formátování Markdownu pro mluvení (BUG 3)."""

from __future__ import annotations

import pytest

from martin.speech.speech_text_formatter import (
    to_speech_text,
    strip_code_blocks,
    strip_emphasis,
    strip_headings,
    strip_inline_code,
    strip_links,
    strip_list_markers,
    strip_tables,
    normalize_whitespace,
    describe_code_block,
)


class TestBasicMarkdown:
    def test_bold_is_removed(self):
        assert to_speech_text("**Ahoj!**") == "Ahoj!"

    def test_bold_whole_sentence(self):
        assert (
            to_speech_text("**Jasně, spouštím Microsoft Flight Simulator.**")
            == "Jasně, spouštím Microsoft Flight Simulator."
        )

    def test_heading_marker_removed(self):
        assert to_speech_text("### Výsledek") == "Výsledek"

    def test_list_marker_removed(self):
        assert to_speech_text("- Otevři aplikaci") == "Otevři aplikaci"

    def test_numbered_list_marker_removed(self):
        assert to_speech_text("1. První bod") == "První bod"

    def test_task_list_marker_removed(self):
        assert to_speech_text("- [x] hotová úloha") == "hotová úloha"

    def test_italic_removed(self):
        assert to_speech_text("Text s *kurzívou* zde.") == "Text s kurzívou zde."

    def test_underscore_italic_removed(self):
        assert to_speech_text("Text s _kurzívou_ zde.") == "Text s kurzívou zde."

    def test_bold_italic_removed(self):
        assert to_speech_text("***Tak silně.***") == "Tak silně."

    def test_strikethrough_removed(self):
        assert to_speech_text("~~přeškrtnuté~~") == "přeškrtnuté"

    def test_horizontal_rule_removed(self):
        assert to_speech_text("---").strip() == ""

    def test_blockquote_marker_removed(self):
        assert to_speech_text("> citace") == "citace"

    def test_no_markdown_symbols_remain(self):
        """Základní pojistka - vysledek nesmí obsahovat Markdown."""
        source = "**Tučné** *kurzíva* `code` [odkaz](http://x.cz) # nadpis"
        result = to_speech_text(source)
        for symbol in ("**", "##", "`", "](", "]("):
            assert symbol not in result


class TestPreservation:
    def test_czech_diacritics_preserved(self):
        assert to_speech_text("Příliš žluťoučký kůň úpěl ďábelské ódy") == (
            "Příliš žluťoučký kůň úpěl ďábelské ódy"
        )

    def test_numbers_preserved(self):
        assert to_speech_text("Cena je 250 Kč") == "Cena je 250 Kč"

    def test_decimal_number_preserved(self):
        assert to_speech_text("Cena je 12.50 EUR") == "Cena je 12.50 EUR"

    def test_punctuation_preserved(self):
        assert to_speech_text("Hotovo! Zda se? Ano, jistě.") == (
            "Hotovo! Zda se? Ano, jistě."
        )

    def test_technical_terms_preserved(self):
        result = to_speech_text("Použij **OpenGL** a `CUDA`.")
        assert "OpenGL" in result
        assert "CUDA" in result

    def test_domain_not_broken(self):
        assert to_speech_text("Odkaz na martin.ai") == "Odkaz na martin.ai"

    def test_empty_input(self):
        assert to_speech_text("") == ""
        assert to_speech_text("   ") == ""


class TestCodeBlocks:
    def test_code_block_described_not_read(self):
        result = to_speech_text("```python\ndef foo():\n    return 1\n```")
        assert "def" not in result
        assert "blok kódu" in result

    def test_inline_code_keeps_content(self):
        assert to_speech_text("Použij `start()`") == "Použij start()"

    def test_describe_empty_block(self):
        assert "prázdný" in describe_code_block("")

    def test_describe_single_line(self):
        assert "jedním řádkem" in describe_code_block("x = 1")

    def test_strip_code_blocks_keeps_surrounding(self):
        result = strip_code_blocks("Před ```x=1``` po")
        assert "Před" in result and "po" in result


class TestLinks:
    def test_link_text_used(self):
        result = to_speech_text("Podívej se na [dokumentaci](https://example.com/docs).")
        assert "dokumentaci" in result
        assert "example.com" not in result

    def test_bare_url_becomes_speech(self):
        result = to_speech_text("Navštiv https://example.com/x")
        assert "odkaz na example.com" in result

    def test_www_stripped(self):
        result = to_speech_text("https://www.example.com/x")
        assert "www" not in result


class TestTables:
    def test_table_becomes_key_value(self):
        source = "| Aplikace | Stav |\n|---|---|\n| MSFS | běží |"
        result = to_speech_text(source)
        assert "MSFS" in result
        assert "běží" in result
        assert "|" not in result

    def test_table_no_pipes_in_result(self):
        source = "| A | B |\n|---|---|\n| 1 | 2 |"
        assert "|" not in to_speech_text(source)


class TestStreamingSafety:
    def test_trailing_space_preserved_when_requested(self):
        result = to_speech_text("Ahoj ", max_chars=0, keep_trailing_space=True)
        assert result.endswith(" ")

    def test_trailing_space_stripped_by_default(self):
        result = to_speech_text("Ahoj ", max_chars=0)
        assert not result.endswith(" ")

    def test_split_chunks_do_not_glue_words(self):
        """Dva chunky nesmi vytvorit 'spustimMicrosoft'."""
        from martin.speech.streaming_tts import StreamingTTS

        class FakeTTS:
            def __init__(self):
                self.synthesized = []
                self._output_device = ""

            def synthesize(self, text):
                self.synthesized.append(text)
                return type("R", (), {"ok": True, "audio_path": "", "error": ""})()

            def stop(self):
                pass

        fake = FakeTTS()
        streamer = StreamingTTS(fake)
        streamer.push_text("Jasně, spouštím ")
        streamer.push_text("Microsoft Flight Simulator. ")
        for text in fake.synthesized:
            assert "spouštímMicrosoft" not in text


class TestTruncation:
    def test_long_text_truncated(self):
        source = "Věta. " * 200
        result = to_speech_text(source, max_chars=100)
        assert len(result) <= 110

    def test_truncation_ends_on_sentence(self):
        source = "První věta je dlouhá. Druhá věta je také dlouhá. Třetí věta."
        result = to_speech_text(source, max_chars=40)
        assert result.endswith(".")