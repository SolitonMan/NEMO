from django.core.management import BaseCommand

from NEMO.views.calendar import do_email_reservation_reminders


class Command(BaseCommand):
	help = (
		"Run every minute to cancel unused reservations and mark them as missed. "
		"Only applicable to areas or tools having a missed reservation threshold value."
	)

	def handle(self, *args, **options):
		do_email_reservation_reminders()
