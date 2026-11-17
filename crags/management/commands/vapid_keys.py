"""Print a new key pair for web push, as lines for the .env file.

    python manage.py vapid_keys

Keep the private key secret. Changing the pair later makes every device's
push subscription invalid: people have to turn notifications on again.
"""
import base64

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from django.core.management.base import BaseCommand


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class Command(BaseCommand):
    help = "Print a new VAPID key pair for web push (.env lines)."

    def handle(self, *args, **options):
        private = ec.generate_private_key(ec.SECP256R1())
        raw_private = private.private_numbers().private_value.to_bytes(32, "big")
        raw_public = private.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        self.stdout.write(f"VAPID_PUBLIC_KEY={b64url(raw_public)}")
        self.stdout.write(f"VAPID_PRIVATE_KEY={b64url(raw_private)}")
