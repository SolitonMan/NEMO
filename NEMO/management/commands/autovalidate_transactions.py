from django.core.management import BaseCommand

from NEMO.scheduler import daily_validate_transactions

class Command(BaseCommand):
	help = (
		"Run nightly to update outstanding transactions"
	)

	def handle(self, *args, **options):
		daily_validate_transactions()
