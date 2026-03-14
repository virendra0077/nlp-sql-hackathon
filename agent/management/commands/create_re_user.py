"""
agent/management/commands/create_re_user.py

Creates a RE Insight user with a securely hashed password.

Usage:
    python manage.py create_re_user --username admin --password secret123
    python manage.py create_re_user --username viewer --password pass --no-staff
"""

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

User = get_user_model()


class Command(BaseCommand):
    help = "Create a RE Insight user with an encrypted password stored in the DB."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True, help="Login username")
        parser.add_argument("--password", required=True, help="Plain-text password (will be hashed)")
        parser.add_argument("--email",    default="",    help="Optional email address")
        parser.add_argument(
            "--no-staff",
            action="store_true",
            help="Create a non-staff user (default: staff=True so they can access /admin/)",
        )
        parser.add_argument(
            "--superuser",
            action="store_true",
            help="Grant superuser privileges",
        )

    def handle(self, *args, **options):
        username   = options["username"]
        password   = options["password"]
        email      = options["email"]
        is_staff   = not options["no_staff"]
        is_super   = options["superuser"]

        if User.objects.filter(username=username).exists():
            raise CommandError(f"User '{username}' already exists.")

        # Validate password strength against Django's validators
        try:
            validate_password(password)
        except ValidationError as e:
            raise CommandError(f"Password validation failed: {'; '.join(e.messages)}")

        user = User.objects.create_user(
            username=username,
            password=password,   # Django hashes this with BCryptSHA256 (see settings)
            email=email,
            is_staff=is_staff,
            is_superuser=is_super,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"✓ User '{user.username}' created successfully.\n"
                f"  Password stored as: {user.password[:20]}…  (BCrypt hash)\n"
                f"  is_staff={user.is_staff}  is_superuser={user.is_superuser}"
            )
        )