import csv
import os
from calendar import monthrange
from datetime import timedelta, datetime
from email import encoders
from email.mime.base import MIMEBase
from io import BytesIO
from typing import Tuple, List, Dict, Set

from PIL import Image
from dateutil import parser
from dateutil.parser import parse
from dateutil.rrule import MONTHLY, rrule
from django.utils.timezone import localtime
from django.core import mail
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.core.mail import EmailMessage
from django.db.models import QuerySet
from django.http import HttpResponse
from django.utils import timezone
from django.utils.timezone import localtime


def bootstrap_primary_color(color_type):
	if color_type == 'success':
		return '#5cb85c'
	elif color_type == 'info':
		return '#5bc0de'
	elif color_type == 'warning':
		return '#f0ad4e'
	elif color_type == 'danger':
		return '#d9534f'
	return None


class EmailCategory(object):
	GENERAL = 0
	SYSTEM = 1
	DIRECT_CONTACT = 2
	BROADCAST_EMAIL = 3
	TIMED_SERVICES = 4
	FEEDBACK = 5
	ABUSE = 6
	SAFETY = 7
	TASKS = 8
	Choices = (
		(GENERAL, "General"),
		(SYSTEM, "System"),
		(DIRECT_CONTACT, "Direct Contact"),
		(BROADCAST_EMAIL, "Broadcast Email"),
		(TIMED_SERVICES, "Timed Services"),
		(FEEDBACK, "Feedback"),
		(ABUSE, "Abuse"),
		(SAFETY, "Safety"),
		(TASKS, "Tasks"),
	)

class SettingType(object):
	BOOLEAN = "Boolean"
	INTEGER = "Integer"
	STRING = "String"
	FLOAT = "Float"
	Choices = (
		(BOOLEAN, "Boolean"),
		(INTEGER, "Integer"),
		(STRING, "String"),
		(FLOAT, "Float"),
	)


def parse_start_and_end_date(start, end):
	start = timezone.make_aware(parser.parse(start), timezone.get_current_timezone())
	end = timezone.make_aware(parser.parse(end), timezone.get_current_timezone())
	end += timedelta(days=1, seconds=-1)  # Set the end date to be midnight by adding a day.
	return start, end


def quiet_int(value_to_convert, default_upon_failure=0):
	"""
	Attempt to convert the given value to an integer. If there is any problem
	during the conversion, simply return 'default_upon_failure'.
	"""
	result = default_upon_failure
	try:
		result = int(value_to_convert)
	except:
		pass
	return result


def parse_parameter_string(parameter_dictionary, parameter_key, maximum_length=3000, raise_on_error=False, default_return=''):
	"""
	Attempts to parse a string from an HTTP GET or POST dictionary and applies validation checks.
	"""
	try:
		parameter = parameter_dictionary[parameter_key].strip()
		if raise_on_error and len(parameter) > maximum_length:
			raise Exception('The parameter named {} is {} characters long, exceeding the maximum length of {} characters.'.format(parameter_key, len(parameter), maximum_length))
		return parameter
	except Exception as e:
		if raise_on_error:
			raise e
		return default_return


def month_list(since=datetime(year=2020, month=7, day=1)):
	month_count = (timezone.now().year - since.year) * 12 + (timezone.now().month - since.month) + 2
	result = list(rrule(MONTHLY, dtstart=since, count=month_count))
	result = localize(result)
	result.reverse()
	return result


def get_month_timeframe(date):
	if date:
		start = parse(date)
	else:
		start = timezone.now()
#	first_of_the_month = localize(datetime(start.year, start.month, 1))
#	last_of_the_month = localize(datetime(start.year, start.month, monthrange(start.year, start.month)[1], 23, 59, 59, 0))

	start_month = start.month
	start_day = start.day

	if start_day > 24:
		if start_month < 12:
			start_month += 1
		else:
			start_month = 1

	if start_month > 1:
		first_of_the_month = localize(datetime(start.year, start_month-1, 25))
	else:
		first_of_the_month = localize(datetime(start.year-1, 12, 25))
	last_of_the_month = localize(datetime(start.year, start_month, 24, 23, 59, 59, 0))

	return first_of_the_month, last_of_the_month


def extract_times(parameters, input_timezone=None):
	"""
	Extract the "start" and "end" parameters from an HTTP request while performing a few logic validation checks.
	The function assumes the UNIX timestamp is in the local timezone. Use input_timezone to specify the timezone.
	"""
	try:
		start = parameters['start']
	except:
		raise Exception("The request parameters did not contain a start time.")

	try:
		end = parameters['end']
	except:
		raise Exception("The request parameters did not contain an end time.")

	try:
		start = float(start)
		start = datetime.utcfromtimestamp(start)
		start = localize(start, input_timezone)
	except:
		raise Exception("The request parameters did not have a valid start time.")

	try:
		end = float(end)
		end = datetime.utcfromtimestamp(end)
		end = localize(end, input_timezone)
	except:
		raise Exception("The request parameters did not have a valid end time.")

	if end < start:
		raise Exception("The request parameters have an end time that precedes the start time.")

	return start, end


def extract_date(date):
	return localize(datetime.strptime(date, '%Y-%m-%d'))


def extract_dates(parameters):
	"""
	Extract the "start" and "end" parameters from an HTTP request while performing a few logic validation checks.
	"""
	try:
		start = parameters['start']
	except:
		raise Exception("The request parameters did not contain a start time.")

	try:
		end = parameters['end']
	except:
		raise Exception("The request parameters did not contain an end time.")

	try:
		start = extract_date(start)
	except:
		raise Exception("The request parameters did not have a valid start time.")

	try:
		end = extract_date(end)
	except:
		raise Exception("The request parameters did not have a valid end time.")

	if end < start:
		raise Exception("The request parameters have an end time that precedes the start time.")

	return start, end


def format_datetime(universal_time):
	local_time = universal_time.astimezone(timezone.get_current_timezone())
	day = int(local_time.strftime("%d"))
	if 4 <= day <= 20 or 24 <= day <= 30:
		suffix = "th"
	else:
		suffix = ["st", "nd", "rd"][day % 10 - 1]
	return local_time.strftime("%A, %B ") + str(day) + suffix + local_time.strftime(", %Y @ ") + local_time.strftime("%I:%M %p").lstrip('0')


def localize(dt, tz=None):
	tz = tz or timezone.get_current_timezone()
	if isinstance(dt, list):
		return [tz.localize(d) for d in dt]
	else:
		return tz.localize(dt)


def naive_local_current_datetime():
	return timezone.now().replace(tzinfo=None)
	#return localtime(timezone.now()).replace(tzinfo=None)


def beginning_of_the_day(t, in_local_timezone=True):
	""" Returns the BEGINNING of today's day (12:00:00.000000 AM of the current day) in LOCAL time. """
	midnight = t.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
	return localize(midnight) if in_local_timezone else midnight


def end_of_the_day(t, in_local_timezone=True):
	""" Returns the END of today's day (11:59:59.999999 PM of the current day) in LOCAL time. """
	midnight = t.replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=None)
	return localize(midnight) if in_local_timezone else midnight

def send_mail(subject, content, from_email, to=None, bcc=None, cc=None, attachments=None, email_category:EmailCategory = EmailCategory.GENERAL, fail_silently=False) -> int:
	mail_msg = EmailMessage(
		subject=subject, body=content, from_email=from_email, to=to, bcc=bcc, cc=cc, attachments=attachments
	)
	mail_msg.content_subtype = "html"
	msg_sent = 0
	#if mail.recipients():
	if to or bcc or cc:
		#email_record = create_email_log(mail_msg, email_category)
		try:
			#msg_sent = mail.send()
			msg_sent = mail.send_mail(subject, content, from_email, to, html_message=content)
			if msg_sent > 0:
				email_record = create_email_log(mail_msg, email_category)
			else:
				raise Exception("Message failed to send")
		except:
			mail_msg.subject = "MESSAGE FAILED TO SEND  -  " + mail_msg.subject
			email_record = create_email_log(mail_msg, email_category)
			email_record.ok = False
			if not fail_silently:
				raise
		finally:
			email_record.save()
	return msg_sent


def create_email_log(email: EmailMessage, email_category: EmailCategory):
	from NEMO.models import EmailLog
	email_record: EmailLog = EmailLog.objects.create(category=email_category, sender=email.from_email, to=', '.join(email.recipients()), subject=email.subject, content=email.body)
	if email.attachments:
		email_attachments = []
		for attachment in email.attachments:
			if isinstance(attachment, MIMEBase):
				email_attachments.append(attachment.get_filename() or '')
		if email_attachments:
			email_record.attachments = ', '.join(email_attachments)
	return email_record


def create_email_attachment(stream, filename=None, maintype="application", subtype="octet-stream", **content_type_params) -> MIMEBase:
	attachment = MIMEBase(maintype, subtype, **content_type_params)
	attachment.set_payload(stream.read())
	encoders.encode_base64(attachment)
	if filename:
		attachment.add_header("Content-Disposition", f'attachment; filename="{filename}"')
	return attachment
