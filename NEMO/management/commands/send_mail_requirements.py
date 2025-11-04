from django.core.management.base import BaseCommand
from django.db.models import F
from django.utils import timezone
from datetime import timedelta

from NEMO.models import Requirement, UserRequirementProgress
from NEMO.utilities import send_mail


class Command(BaseCommand):
	help = (
		"Check user requirements and send emails as needed"
	)

	def handle(self, *args, **options):
		now = timezone.now()
		status_type = ['not_started', 'in_progress', 'expired']

		records = UserRequirementProgress.objects.filter(status__in=status_type)

		for record in records:
			Requirement = record.requirement
			notification_interval = Requirement.notification_interval 
			Reminders_time = now - timedelta(days=notification_interval)
			resource_link = Requirement.resource_link

			if record.last_notified is None or record.last_notified < Reminders_time:
				if record.updated and (record.last_notified is None or record.updated <= record.last_notified):
					status_message = {
						'not_started': 'not started','in_progress': 'in progress','expired': 'expired'
						}
					message_text = (
						f"Dear {getattr(record.user, 'name', getattr(record.user, 'get_full_name', record.user))},\n\n"
						f"Our records indicate that your requirement '{getattr(record.requirement, 'name', record.requirement)}' is currently '{status_message.get(record.status, record.status)}'. "
						f"Please complete it at your earliest convenience."
						f"\n\nYou can find more information and access the necessary resources here: {resource_link}."
						"\n\nBest regards,\nAdmin Team"
					)
					send_mail(
						"Reminder: User Requirement Pending",
						message_text,
						"LEOHelp@psu.edu",
						to=[record.user.email],
						fail_silently=False,
					)
					record.last_notified = now
					record.updated = now
					record.save()