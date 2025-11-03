from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from NEMO.models import UserRequirementProgress
from NEMO.utilities import send_mail


class Command(BaseCommand):
    help = (
        "Check user requirements and send emails as needed"
    )

    def handle(self, *args, **options):
        now = timezone.now()
        one_week_ago = now - timedelta(days=7)
        reminder_time = now - timedelta(days=7)

        status_type = ['not_started', 'in_progress', 'expired']

        records = UserRequirementProgress.objects.filter(status__in=status_type)

        for record in records:
            if record.created and record.created < reminder_time:
                if not record.last_notified or record.last_notified < one_week_ago:
                    status_message = {
                        'not_started': 'not started','in_progress': 'in progress','expired': 'expired'
                        }
                    message_text = (
                        f"Dear {getattr(record.user, 'name', getattr(record.user, 'get_full_name', record.user))},\n\n"
                        f"Our records indicate that your requirement '{getattr(record.requirement, 'name', record.requirement)}' is currently '{status_message.get(record.status, record.status)}'. "
                        f"You have a pending user requirement: {getattr(record.requirement, 'name', record.requirement)}. "
                        "Please complete it at your earliest convenience.\n\nBest regards,\nAdmin Team"
                    )
                    send_mail(
                        "Reminder: User Requirement Pending",
                        message_text,
                        "LEOHelp@psu.edu",
                        to=[record.user.email],
                        fail_silently=False,
                    )
                    record.last_notified = now
                    record.save()




