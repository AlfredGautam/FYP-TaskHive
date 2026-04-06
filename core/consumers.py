import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model


class NotificationConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer — joins user-specific room + team room for real-time updates."""

    async def connect(self):
        self.rooms = []
        user = self.scope.get("user")

        if not user or user.is_anonymous:
            await self.close()
            return

        # Always join a personal room so invitations can reach this user
        user_room = f"user_{user.id}"
        self.rooms.append(user_room)
        await self.channel_layer.group_add(user_room, self.channel_name)

        # Also join team room if the user is in a team
        team_id = await self._get_team_id(user)
        if team_id:
            team_room = f"team_{team_id}"
            self.rooms.append(team_room)
            await self.channel_layer.group_add(team_room, self.channel_name)

        await self.accept()

    async def disconnect(self, close_code):
        for room in self.rooms:
            await self.channel_layer.group_discard(room, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        pass

    # ---- handlers for group_send messages ----

    async def new_notification(self, event):
        await self.send(text_data=json.dumps({
            "type": "new_notification",
            "payload": event.get("payload", {}),
        }))

    async def data_changed(self, event):
        await self.send(text_data=json.dumps({
            "type": "data_changed",
            "payload": event.get("payload", {}),
        }))

    # ---- helpers ----

    @database_sync_to_async
    def _get_team_id(self, user):
        from core.models import TeamMembership
        m = TeamMembership.objects.filter(user=user).first()
        return m.team_id if m else None
