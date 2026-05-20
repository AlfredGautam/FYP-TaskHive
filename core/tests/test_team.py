"""
Unit tests for team management APIs:
  - Team create, join, leave, delete
  - Invite, promote, demote, remove member
  - Permissions (head vs member)
"""
import json

from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User

from core.models import Team, TeamMembership, TeamInvitation, UserProfile


LOCMEM_CACHE = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "test-team"}}


def _post_json(client, url, payload):
    return client.post(url, json.dumps(payload), content_type="application/json")


@override_settings(CACHES=LOCMEM_CACHE)
class TeamCreateTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=False)
        self.user = User.objects.create_user(
            username="alice@example.com", email="alice@example.com", password="pass123"
        )
        self.client.login(username="alice@example.com", password="pass123")

    def test_create_team(self):
        resp = _post_json(self.client, "/api/team/create/", {"name": "Alpha Team"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["team"]["name"], "Alpha Team")
        self.assertEqual(data["role"], "head")

        team = Team.objects.get(id=data["team"]["id"])
        membership = TeamMembership.objects.get(team=team, user=self.user)
        self.assertEqual(membership.role, "head")

    def test_create_team_no_name(self):
        resp = _post_json(self.client, "/api/team/create/", {"name": ""})
        self.assertEqual(resp.status_code, 400)

    def test_create_team_unauthenticated(self):
        self.client.logout()
        resp = _post_json(self.client, "/api/team/create/", {"name": "Fail Team"})
        self.assertEqual(resp.status_code, 302)  # redirect to login


@override_settings(CACHES=LOCMEM_CACHE)
class TeamJoinTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=False)
        self.owner = User.objects.create_user(
            username="owner@example.com", email="owner@example.com", password="pass123"
        )
        self.joiner = User.objects.create_user(
            username="joiner@example.com", email="joiner@example.com", password="pass123"
        )
        self.team = Team.objects.create(name="Test Team", code="JOIN-TEST", created_by=self.owner)
        TeamMembership.objects.create(team=self.team, user=self.owner, role="head")

    def test_join_by_code(self):
        self.client.login(username="joiner@example.com", password="pass123")
        resp = _post_json(self.client, "/api/team/join/", {"code": "JOIN-TEST"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertTrue(TeamMembership.objects.filter(team=self.team, user=self.joiner).exists())

    def test_join_invalid_code(self):
        self.client.login(username="joiner@example.com", password="pass123")
        resp = _post_json(self.client, "/api/team/join/", {"code": "NOPE-0000"})
        data = resp.json()
        self.assertFalse(data["ok"])

    def test_join_already_member(self):
        TeamMembership.objects.create(team=self.team, user=self.joiner, role="member")
        self.client.login(username="joiner@example.com", password="pass123")
        resp = _post_json(self.client, "/api/team/join/", {"code": "JOIN-TEST"})
        data = resp.json()
        # Should indicate already a member (not an error, but ok with note)
        self.assertTrue(data["ok"])


@override_settings(CACHES=LOCMEM_CACHE)
class TeamLeaveTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=False)
        self.owner = User.objects.create_user(
            username="owner@example.com", email="owner@example.com", password="pass123"
        )
        self.member = User.objects.create_user(
            username="member@example.com", email="member@example.com", password="pass123"
        )
        self.team = Team.objects.create(name="Leave Team", code="LEAVE-01", created_by=self.owner)
        TeamMembership.objects.create(team=self.team, user=self.owner, role="head")
        TeamMembership.objects.create(team=self.team, user=self.member, role="member")

        # Set current_team for the member
        profile = UserProfile.objects.get(user=self.member)
        profile.current_team = self.team
        profile.save()

    def test_member_can_leave(self):
        self.client.login(username="member@example.com", password="pass123")
        resp = _post_json(self.client, "/api/team/leave/", {})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertFalse(TeamMembership.objects.filter(team=self.team, user=self.member).exists())


@override_settings(CACHES=LOCMEM_CACHE)
class TeamInviteTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=False)
        self.head = User.objects.create_user(
            username="head@example.com", email="head@example.com", password="pass123"
        )
        self.member = User.objects.create_user(
            username="member@example.com", email="member@example.com", password="pass123"
        )
        self.target = User.objects.create_user(
            username="target@example.com", email="target@example.com", password="pass123"
        )
        self.team = Team.objects.create(name="Invite Team", code="INV-0001", created_by=self.head)
        TeamMembership.objects.create(team=self.team, user=self.head, role="head")
        TeamMembership.objects.create(team=self.team, user=self.member, role="member")

    def test_head_can_invite(self):
        self.client.login(username="head@example.com", password="pass123")
        resp = _post_json(self.client, "/api/team/invite/", {
            "team_id": self.team.id,
            "email": "target@example.com",
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])

    def test_member_cannot_invite(self):
        self.client.login(username="member@example.com", password="pass123")
        resp = _post_json(self.client, "/api/team/invite/", {
            "team_id": self.team.id,
            "email": "target@example.com",
        })
        self.assertEqual(resp.status_code, 403)

    def test_invite_nonexistent_user(self):
        self.client.login(username="head@example.com", password="pass123")
        resp = _post_json(self.client, "/api/team/invite/", {
            "team_id": self.team.id,
            "email": "ghost@example.com",
        })
        self.assertEqual(resp.status_code, 404)


@override_settings(CACHES=LOCMEM_CACHE)
class TeamPromoteDemoteTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=False)
        self.head = User.objects.create_user(
            username="head@example.com", email="head@example.com", password="pass123"
        )
        self.member = User.objects.create_user(
            username="member@example.com", email="member@example.com", password="pass123"
        )
        self.team = Team.objects.create(name="Promote Team", code="PROMO-01", created_by=self.head)
        TeamMembership.objects.create(team=self.team, user=self.head, role="head")
        TeamMembership.objects.create(team=self.team, user=self.member, role="member")

        profile = UserProfile.objects.get(user=self.head)
        profile.current_team = self.team
        profile.save()

    def test_promote_member(self):
        self.client.login(username="head@example.com", password="pass123")
        resp = _post_json(self.client, "/api/team/member/promote/", {
            "team_id": self.team.id,
            "member_email": "member@example.com",
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        membership = TeamMembership.objects.get(team=self.team, user=self.member)
        self.assertEqual(membership.role, "head")

    def test_member_cannot_promote(self):
        self.client.login(username="member@example.com", password="pass123")
        # Set member's current_team
        profile = UserProfile.objects.get(user=self.member)
        profile.current_team = self.team
        profile.save()

        resp = _post_json(self.client, "/api/team/member/promote/", {
            "team_id": self.team.id,
            "member_email": "head@example.com",
        })
        self.assertEqual(resp.status_code, 403)

    def test_demote_admin(self):
        # First promote the member
        TeamMembership.objects.filter(team=self.team, user=self.member).update(role="head")

        self.client.login(username="head@example.com", password="pass123")
        resp = _post_json(self.client, "/api/team/member/demote/", {
            "team_id": self.team.id,
            "member_email": "member@example.com",
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        membership = TeamMembership.objects.get(team=self.team, user=self.member)
        self.assertEqual(membership.role, "member")


@override_settings(CACHES=LOCMEM_CACHE)
class TeamDeleteTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=False)
        self.owner = User.objects.create_user(
            username="owner@example.com", email="owner@example.com", password="pass123"
        )
        self.member = User.objects.create_user(
            username="member@example.com", email="member@example.com", password="pass123"
        )
        self.team = Team.objects.create(name="Delete Team", code="DEL-0001", created_by=self.owner)
        TeamMembership.objects.create(team=self.team, user=self.owner, role="head")
        TeamMembership.objects.create(team=self.team, user=self.member, role="member")

    def test_head_can_delete_team(self):
        # Set current_team
        profile = UserProfile.objects.get(user=self.owner)
        profile.current_team = self.team
        profile.save()

        self.client.login(username="owner@example.com", password="pass123")
        resp = _post_json(self.client, "/api/team/delete/", {"team_id": self.team.id})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertFalse(Team.objects.filter(id=self.team.id).exists())

    def test_member_cannot_delete_team(self):
        profile = UserProfile.objects.get(user=self.member)
        profile.current_team = self.team
        profile.save()

        self.client.login(username="member@example.com", password="pass123")
        resp = _post_json(self.client, "/api/team/delete/", {"team_id": self.team.id})
        self.assertEqual(resp.status_code, 403)


@override_settings(CACHES=LOCMEM_CACHE)
class TeamRemoveMemberTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=False)
        self.head = User.objects.create_user(
            username="head@example.com", email="head@example.com", password="pass123"
        )
        self.member = User.objects.create_user(
            username="member@example.com", email="member@example.com", password="pass123"
        )
        self.team = Team.objects.create(name="Remove Team", code="REM-0001", created_by=self.head)
        TeamMembership.objects.create(team=self.team, user=self.head, role="head")
        TeamMembership.objects.create(team=self.team, user=self.member, role="member")

    def test_head_can_remove_member(self):
        self.client.login(username="head@example.com", password="pass123")
        resp = _post_json(self.client, "/api/team/member/remove/", {
            "team_id": self.team.id,
            "member_email": "member@example.com",
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertFalse(TeamMembership.objects.filter(team=self.team, user=self.member).exists())

    def test_member_cannot_remove(self):
        self.client.login(username="member@example.com", password="pass123")
        resp = _post_json(self.client, "/api/team/member/remove/", {
            "team_id": self.team.id,
            "member_email": "head@example.com",
        })
        self.assertEqual(resp.status_code, 403)
