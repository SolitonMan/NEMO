from django.core.management import BaseCommand

from NEMO.scheduler import pulse_interlocks

class Command(BaseCommand):
	help = (
		"Run every minute to pulse all interlocks not currently in use"
	)

	def handle(self, *args, **options):
		pulse_interlocks()
