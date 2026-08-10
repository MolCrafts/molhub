"""Tests for the source driver protocols."""

from molhub.sources import HttpsSource, PublishingSource
from molhub.sources.drivers.figshare import FigshareSource
from molhub.sources.drivers.huggingface import HuggingFaceSource


class TestPublishingSource:
    def test_publishing_drivers_satisfy_the_protocol(self):
        assert isinstance(FigshareSource(), PublishingSource)
        assert isinstance(HuggingFaceSource(), PublishingSource)

    def test_read_only_driver_does_not_satisfy_the_protocol(self):
        assert not isinstance(HttpsSource(), PublishingSource)
