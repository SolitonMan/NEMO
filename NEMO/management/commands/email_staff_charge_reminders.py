from django.core.management import BaseCommand

from NEMO.views.staff_charges import email_staff_charge_reminders


class Command(BaseCommand):
	help = (
		"Run every minute to cancel unused reservations and mark them as missed. "
		"Only applicable to areas or tools having a missed reservation threshold value."
	)

	def handle(self, *args, **options):
		email_staff_charge_reminders()
