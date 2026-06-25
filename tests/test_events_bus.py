from unittest.mock import MagicMock

from app.events_bus import EVENTS_CHANNEL, publish_new_events


def test_publish_no_op_on_zero():
    client = MagicMock()
    publish_new_events(0, client=client)
    client.publish.assert_not_called()


def test_publish_sends_count():
    client = MagicMock()
    publish_new_events(7, client=client)
    client.publish.assert_called_once_with(EVENTS_CHANNEL, "7")
