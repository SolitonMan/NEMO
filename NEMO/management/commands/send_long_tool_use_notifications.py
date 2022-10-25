from django.core.management import BaseCommand

from NEMO.scheduler import excessive_tool_use_reminder

class Command(BaseCommand):
	help = (
		"Run hourly to remind users who have been logged in to a tool for a longer time than the maximum block time"
	)

	def handle(self, *args, **options):
		excessive_tool_use_reminder()
