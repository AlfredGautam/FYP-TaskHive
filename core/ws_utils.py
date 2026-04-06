"""Helpers to broadcast WebSocket events from sync Django views."""

import logging
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


def broadcast_notification(team_id, payload=None):
    """Send a new_notification event to all connected members of a team."""
    try:
        layer = get_channel_layer()
        if layer is None:
            return
        async_to_sync(layer.group_send)(
            f"team_{team_id}",
            {"type": "new_notification", "payload": payload or {}},
        )
    except Exception as e:
        logger.debug("WS broadcast_notification failed: %s", e)


def broadcast_to_user(user_id, payload=None):
    """Send a new_notification event to a specific user's personal room."""
    try:
        layer = get_channel_layer()
        if layer is None:
            return
        async_to_sync(layer.group_send)(
            f"user_{user_id}",
            {"type": "new_notification", "payload": payload or {}},
        )
    except Exception as e:
        logger.debug("WS broadcast_to_user failed: %s", e)


def broadcast_data_changed(team_id, payload=None):
    """Tell all connected clients in a team to reload their workspace data."""
    try:
        layer = get_channel_layer()
        if layer is None:
            return
        async_to_sync(layer.group_send)(
            f"team_{team_id}",
            {"type": "data_changed", "payload": payload or {}},
        )
    except Exception as e:
        logger.debug("WS broadcast_data_changed failed: %s", e)
