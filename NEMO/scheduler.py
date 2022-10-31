from datetime import datetime, timedelta
from logging import getLogger
from schedule import Scheduler
import threading
import time

from django.conf import settings
from django.core import mail
from django.utils import timezone
from django.utils.html import strip_tags

from NEMO.models import Interlock, Tool, UsageEvent, StaffCharge, AreaAccessRecord, ConsumableWithdraw, GlobalFlag, ProbationaryQualifications, ToolUseNotificationLog

#end_run = None
def update_probationary_users():
	date_now = timezone.now()
	d1 = datetime.strptime(date_now,"%Y-%m-%d")
	probationary_qualifications = ProbationaryQualifications.objects.all()

	for pq in probationary_qualifications:
		if pq.tool_last_used is not None:
			d2 = datetime.strptime(pq.tool_last_used,"%Y-%m-%d")
			if abs((d1-d2).days) > 182:
				pq.probationary_user = True
				pq.save()
		elif pq.qualification_date is not None:
			d2 = datetime.strptime(pq.qualification_date,"%Y-%m-%d")
			if abs((d1-d2).days) > 182:
				pq.probationary_user = True
				pq.save()


def pulse_interlocks():
	logger = getLogger(__name__)

	tools = Tool.objects.all()
	for t in tools:
		if not t.in_use():
			if t.interlock is not None:
				t.interlock.pulse()


def update_autologout():
	logger = getLogger(__name__)
	usage_events = UsageEvent.objects.filter(set_for_autologout=True, end=None, end_time__lt=timezone.now())
	for u in usage_events:
		u.end = u.end_time
		u.updated = timezone.now()
		u.save()


def daily_validate_transactions():
	print("Daily transaction validation started at " + str(datetime.now()))
	validation_date = datetime.now()-timedelta(days=5)
	print("Running validation for transactions older than " + str(validation_date))

	# validate usage events
	usage_events = UsageEvent.objects.filter(end__lte=validation_date, validated=False, contested=False, active_flag=True)

	print("Found " + str(usage_events.count()) + " usage event transactions to validate.")

	for u in usage_events:
		u.auto_validate()

	# validate staff charges
	staff_charges = StaffCharge.objects.filter(end__lte=validation_date, validated=False, contested=False, active_flag=True)

	print("Found " + str(staff_charges.count()) + " staff charge transactions to validate.")

	for s in staff_charges:
		s.auto_validate()

	# validate area access records
	area_access_records = AreaAccessRecord.objects.filter(end__lte=validation_date, validated=False, contested=False, active_flag=True)

	print("Found " + str(area_access_records.count()) + " area access record transactions to validate.")

	for a in area_access_records:
		a.auto_validate()

	# validate consumable withdraws
	consumable_withdraws = ConsumableWithdraw.objects.filter(date__lte=validation_date, validated=False, contested=False, active_flag=True)

	print("Found " + str(consumable_withdraws.count()) + " consumable withdraw transactions to validate.")

	for c in consumable_withdraws:
		c.auto_validate()

	print("Daily transaction validation completed at " + str(datetime.now()))


def area_access_logout_reminder():
	records = AreaAccessRecord.objects.filter(end=None)
	for r in records:
		if (timezone.now() - r.start) > timedelta(hours=24):
			# send the user a message that they're logged in
			recipient = r.user
			area = r.area
			start = r.start

			subject = "Access to " + str(area) + " since " + str(start)

			message = "<p>Hello " + str(recipient.first_name) + " " + str(recipient.last_name) + ",</p>"
			message += "<p>LEO has detected that you have been logged in to the " + str(area) + " since " + str(start) + ".  If this is intended please ignore this message.  If you didn't intend to be logged in this long, please log out and submit a contest for the resulting Area Access record to correct the error.  If you have any questions please contact LEOHelp@psu.edu.</p>"
			message += "<p>Thank you,<br>The LEO Team</p>"

			mail.send_mail(subject, strip_tags(message), recipient.email, [recipient.email], html_message=message)


def excessive_tool_use_reminder():
	tools = Tool.objects.all()

	if settings.NOTIFICATION_TOOL_USE_EXCESSIVE_INTERVAL is not None:
		last_sent_interval = int(settings.NOTIFICATION_TOOL_USE_EXCESSIVE_INTERVAL)
	else:
		last_sent_interval = 119

	for t in tools:
		if t.in_use():
			if settings.NOTIFICATION_TOOL_USE_EXCESSIVE_DEFAULT_BLOCK is not None:
				use_block_limit = int(settings.NOTIFICATION_TOOL_USE_EXCESSIVE_DEFAULT_BLOCK)
			else:
				use_block_limit = 360

			# see if a related reservation exists for this tool
			usage_event = t.get_current_usage_event()
			if t.maximum_usage_block_time is not None:
				use_block_limit = t.maximum_usage_block_time

			if (timezone.now() - usage_event.start) >= timedelta(minutes=use_block_limit):
				b_send_message = False
				# send a notice if none has been sent recently
				if ToolUseNotificationLog.objects.filter(usage_event=usage_event).exists():
					tunl = ToolUseNotificationLog.objects.filter(usage_event=usage_event).order_by('-sent')
					last_sent = tunl[0].sent
					if timezone.now() - last_sent >= timedelta(minutes=last_sent_interval):
						b_send_message = True
				else:
					b_send_message = True

				if b_send_message:
					recipient = usage_event.operator
					subject = "Use of the " + t.name + " since " + str(usage_event.start)

					message = "<p>Hello " + str(recipient.first_name) + " " + str(recipient.last_name) + ",</p>"
					message += "<p>LEO has detected that you have been logged in to the " + str(t.name) + " since " + str(usage_event.start) + ".  If this is intended please ignore this message.  If you didn't intend to be logged in this long, please log out and submit a contest for the resulting Usage Event record as well as any related Staff Charge, Area Access or Consumable Withdraw records as necessary to correct the error(s).  If you have any questions please contact LEOHelp@psu.edu.</p>"
					message += "<p>Thank you,<br>The LEO Team</p>"

					mail.send_mail(subject, strip_tags(message), recipient.email, [recipient.email], html_message=message)

					tl = ToolUseNotificationLog.objects.create(tool=t, usage_event=usage_event, message=message, sent=timezone.now())
					

# Items below here are deprecated
# They're not being removed just yet
# They may serve as examples for similar needs

def print_status():
	print("schedule is running at " + str(datetime.now()))


def run_continuously(self, interval=1):
	cease_continuous_run = threading.Event()

	class ScheduleThread(threading.Thread):
		@classmethod
		def run(cls):
			while not cease_continuous_run.is_set():
				self.run_pending()
				time.sleep(interval)

	continuous_thread = ScheduleThread()
	continuous_thread.setDaemon(True)
	continuous_thread.start()
	return cease_continuous_run


Scheduler.run_continuously = run_continuously

def start_scheduler():
	now = datetime.now()
	dt_string = now.strftime("%d/%m/%Y %H:%M:%S")

	flag = GlobalFlag.objects.get(name="SchedulerStarted")

	if flag is not None:
		if not flag.active:
			scheduler = Scheduler()
			if scheduler is not None:
				print("start_scheduler called at " + dt_string)
				scheduler.every(1).minutes.do(pulse_interlocks)
				scheduler.every().day.at("22:00").do(daily_validate_transactions)
				scheduler.every(15).minutes.do(print_status)
				#end_run = 
				scheduler.run_continuously()
				flag.active = True
				flag.save()
			else:
				print("There was a problem creatings the Scheduler")
		else:
			print("The scheduler has already been started")
	else:
		print("No global flag named SchedulerStarted has been found")



