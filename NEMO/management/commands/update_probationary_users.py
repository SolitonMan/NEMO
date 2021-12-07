from django.core.management import BaseCommand

from NEMO.scheduler import update_probationary_users

class Command(BaseCommand):
	help = (
		"Run every minute to pulse all interlocks not currently in use"
	)

	def handle(self, *args, **options):
		update_probationary_users()
