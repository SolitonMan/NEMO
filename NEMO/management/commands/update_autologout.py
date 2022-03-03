from django.core.management import BaseCommand

from NEMO.scheduler import update_autologout

class Command(BaseCommand):
	help = (
		"Run every minute to update usage events with set_for_autologout = true"
	)

	def handle(self, *args, **options):
		update_autologout()
