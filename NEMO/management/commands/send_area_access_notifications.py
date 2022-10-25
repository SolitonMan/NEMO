from django.core.management import BaseCommand

from NEMO.scheduler import area_access_logout_reminder

class Command(BaseCommand):
	help = (
		"Run hourly to remind users who have been logged in to an area for more than 24 hours"
	)

	def handle(self, *args, **options):
		area_access_logout_reminder()
