from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from NEMO.models import Reservation, User, UsageEvent, NotificationSchemeToolAction
from NEMO.utilities import send_mail
from NEMO.views.customization import get_media_file_contents



def check_business_hours():
	current_time = timezone.now()
	weekday = current_time.weekday()
	hour = current_time.hour

	if weekday in (0,1,2,3,4) and 8 <= hour <= 17:
		return True
	else:
		return False


@receiver(post_save, sender=User)
def new_user_account_created(sender, instance, created, **kwargs):
	if created:
		# Notify LEOHelp a new account was created
		subject = "New User Account for " + str(instance)
		message = "A new user account has been created for " + str(instance) + ".  Please check the account to ensure it has been appropriately configured."
		msg_from = "LEOHelp@psu.edu"
		msg_to = ["LEOHelp@psu.edu"]
		send_mail(subject, message, msg_from, msg_to)

		# send e welcome message
		msg = get_media_file_contents("new_user_email.htm")
		send_mail("Welcome to LEO", msg, "LEOHelp@psu.edu", [str(instance.email)])


@receiver(pre_save, sender=UsageEvent)
def tool_status_update(sender, instance, **kwargs):
	# temporary shut off of tool status in case of deployment to production of other features
	#try:
	#	return
	#except Exception as e:
	#	return

	current = instance
	if instance.id is not None:
		previous = UsageEvent.objects.get(id=instance.id)
	else:
		previous = None

	if previous is None:
		# tool run just started
		tool = instance.tool
		notification_schemes = NotificationSchemeToolAction.objects.filter(tool=tool)

		for ns in notification_schemes:
			if ns.event == "start" or ns.event == "all":
				# prepare message
				subject = str(tool.name) + " has been started"
				message = str(instance.operator) + " has started a run on the " + str(instance.tool.name)
				msg_from = "LEOHelp@psu.edu"
				if ns.recipient == "primary":
					msg_to = [tool.primary_owner.email]
				elif ns.recipient == "backup":
					msg_to = list(tool.backup_owners.all().values_list("email", flat=True))
				elif ns.recipient == "all":
					msg_to = list(tool.backup_owners.all().values_list("email", flat=True))
					msg_to.append(tool.primary_owner.email)
				else:
					if User.objects.filter(id=int(ns.recipient)).exists():
						msg_to=[User.objects.get(id=int(ns.recipient)).email]


				# check timing
				b_send = False
				frequency = ns.frequency
				cbh = check_business_hours()
				if frequency == "all":
					b_send = True
				if frequency == "business" and cbh:
					b_send = True
				if frequency == "non-business" and not cbh:
					b_send = True
				if b_send:
					send_mail(subject, message, msg_from, msg_to)


	if previous is not None:
		if previous.end is None and current.end is not None:
			# tool run just ended
			tool = instance.tool
			notification_schemes = NotificationSchemeToolAction.objects.filter(tool=tool)

			for ns in notification_schemes:
				if ns.event == "end" or ns.event == "all":
					subject = str(tool.name) + " has been stopped"
					message = str(instance.operator) + " has stopped a run on the " + str(instance.tool.name)
					msg_from = "LEOHelp@psu.edu"

					if ns.recipient == "primary":
						msg_to = [tool.primary_owner.email]
					elif ns.recipient == "backup":
						msg_to = list(tool.backup_owners.all().values_list("email", flat=True))
					elif ns.recipient == "all":
						msg_to = list(tool.backup_owners.all().values_list("email", flat=True))
						msg_to.append(tool.primary_owner.email)
					else:
						if User.objects.filter(id=int(ns.recipient)).exists():
							msg_to=[User.objects.get(id=int(ns.recipient)).email]

					# check timing
					b_send = False
					frequency = ns.frequency
					cbh = check_business_hours()
					if frequency == "all":
						b_send = True
					if frequency == "business" and cbh:
						b_send = True
					if frequency == "non-business" and not cbh:
						b_send = True
					if b_send:
						send_mail(subject, message, msg_from, msg_to)



@receiver(post_save, sender=Reservation)
def reservation_status_update(sender, instance, created, **kwargs):
	return
