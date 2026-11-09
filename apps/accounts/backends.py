from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


class EmailOrUsernameBackend(ModelBackend):
    """Sign in with username, e-mail address, matriculation number or staff ID."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None
        User = get_user_model()
        ident = username.strip()
        candidates = User.objects.filter(
            Q(username__iexact=ident)
            | Q(email__iexact=ident)
            | Q(student__matric_number__iexact=ident)
            | Q(staff_profile__staff_id__iexact=ident)
        ).distinct()
        for user in candidates:
            if user.check_password(password) and self.user_can_authenticate(user):
                return user
        # Mitigate timing attacks distinguishing existing/non-existing users.
        User().set_password(password)
        return None
