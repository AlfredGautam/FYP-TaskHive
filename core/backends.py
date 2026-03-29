from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

UserModel = get_user_model()


class EmailBackend(ModelBackend):
    """
    Authenticate against the email field as well as username.
    Tries username first (default), then falls back to email lookup.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None

        # 1) Try default username lookup
        user = super().authenticate(request, username=username, password=password, **kwargs)
        if user is not None:
            return user

        # 2) Fallback: lookup by email field
        try:
            user = UserModel.objects.get(email__iexact=username)
        except (UserModel.DoesNotExist, UserModel.MultipleObjectsReturned):
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user

        return None
