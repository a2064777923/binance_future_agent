import unittest
from pathlib import Path

from bfa.narrative.rss import RssFeedCollector, parse_feed


FIXTURES = Path(__file__).parent / "fixtures" / "narrative"


class NarrativeRssTests(unittest.TestCase):
    def test_parses_rss_items(self):
        records = parse_feed(
            (FIXTURES / "rss_feed.xml").read_text(encoding="utf-8"),
            source="rss:news.example.test",
            known_symbols=["SOLUSDT"],
            collected_at="2026-06-19T09:01:00Z",
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].source_id, "rss-001")
        self.assertEqual(records[0].author, "newsdesk")
        self.assertEqual(records[0].symbol_mentions, ["BTCUSDT", "SOLUSDT"])

    def test_parses_atom_entries(self):
        records = parse_feed(
            (FIXTURES / "atom_feed.xml").read_text(encoding="utf-8"),
            source="rss:news.example.test",
            collected_at="2026-06-19T10:01:00Z",
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].source_id, "atom-001")
        self.assertEqual(records[0].author, "atomdesk")
        self.assertEqual(records[0].symbol_mentions, ["ESPORTSUSDT"])

    def test_collector_uses_injected_fetcher_and_empty_url_list(self):
        feeds = {
            "https://news.example.test/rss.xml": (FIXTURES / "rss_feed.xml").read_text(encoding="utf-8")
        }

        collector = RssFeedCollector(
            ["https://news.example.test/rss.xml"],
            fetcher=lambda url: feeds[url],
            known_symbols=["SOLUSDT"],
            collected_at="now",
        )

        self.assertEqual(RssFeedCollector([], fetcher=lambda _url: "").collect(), [])
        self.assertEqual(collector.collect()[0].source, "rss:news.example.test")


if __name__ == "__main__":
    unittest.main()

