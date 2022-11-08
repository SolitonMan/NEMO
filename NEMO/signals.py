from django.db.models.signals import post_save
from django.dispatch import receiver

from NEMO.models import User
from NEMO.utilities import send_mail
from NEMO.views.customization import get_media_file_contents

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
