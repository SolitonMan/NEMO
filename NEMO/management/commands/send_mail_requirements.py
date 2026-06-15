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
			rqmt = record.requirement
			notification_interval = rqmt.notification_interval 
			Reminders_time = now - timedelta(days=notification_interval)
			resource_link = rqmt.resource_link

			if record.last_notified is None or record.last_notified < Reminders_time:
				if record.updated and (record.last_notified is None or record.updated <= record.last_notified):
					status_message = {
						'not_started': 'not started','in_progress': 'in progress','expired': 'expired'
						}
					message_text = (
						f"Dear {getattr(record.user, 'first_name', record.user)} {getattr(record.user, 'last_name', record.user)} ,<br><br>"
						f"Our records indicate that your requirement '{getattr(record.requirement, 'name', record.requirement)}' is currently '{status_message.get(record.status, record.status)}'. "
						f"Please complete it at your earliest convenience."
						f"<br><br>You can find more information and access the necessary resources here: {resource_link}."
						"<br><br>Best regards,<br>Admin Team"
					)
					send_mail(
						"TEST - Reminder: User Requirement Pending",
						message_text,
						"LEOHelp@psu.edu",
						to=[record.user.email],
						fail_silently=False,
					)
					record.last_notified = now
					record.updated = now
					record.save()

		# Second query: Completed requirements expiring within 31 days
		expiration_threshold = now + timedelta(days=31)
		expiring_records = UserRequirementProgress.objects.filter(
			status='completed',
			expires_on__lt=expiration_threshold,
			expires_on__gt=now,
			requirement__retrain_interval_days__gt=0,
			requirement__retrain_interval_days__isnull=False
		)

		for record in expiring_records:
			rqmt = record.requirement
			notification_interval = rqmt.notification_interval
			Reminders_time = now - timedelta(days=notification_interval)
			resource_link = rqmt.resource_link

			if record.last_notified is None or record.last_notified < Reminders_time:
				days_until_expiration = (record.expires_on - now).days
				requirement_name = getattr(record.requirement, 'name', record.requirement)
				
				message_text = (
					f"Dear {getattr(record.user, 'first_name', record.user)} {getattr(record.user, 'last_name', record.user)},<br><br>"
					f"This is a reminder that your requirement '{requirement_name}' will expire in {days_until_expiration} day{'s' if days_until_expiration != 1 else ''} "
					f"on {record.expires_on.strftime('%B %d, %Y')}.<br><br>"
					f"Please ensure you complete the retraining before the expiration date to maintain your qualification."
				)
				
				if resource_link:
					message_text += f"<br><br>You can find more information and access the necessary resources here: {resource_link}."
				
				message_text += "<br><br>Best regards,<br>Admin Team"
				
				send_mail(
					f"{requirement_name} is expiring in {days_until_expiration} day{'s' if days_until_expiration != 1 else ''}",
					message_text,
					"LEOHelp@psu.edu",
					to=[record.user.email],
					fail_silently=False,
				)
				record.last_notified = now
				record.updated = now
				record.save()