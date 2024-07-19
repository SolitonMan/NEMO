from datetime import timedelta

from django import template
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse, NoReverseMatch
from django.utils import timezone
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe
from pkg_resources import get_distribution, DistributionNotFound

from NEMO.models import Area, AreaAccessRecord, AreaAccessRecordProject, Consumable, ConsumableWithdraw, StaffCharge, StaffChargeProject, UsageEvent, UsageEventProject
from NEMO.utilities import format_datetime

register = template.Library()

@register.simple_tag
def get_request_user(request):
	return request.user

@register.filter
def class_name(value):
	return value.__class__.__name__


@register.filter
def is_soon(time):
	""" 'Soon' is defined as within 10 minutes from now. """
	return time <= timezone.now() + timedelta(minutes=10)


@register.filter
def to_int(value):
	return int(value)


@register.filter
def json_search_base(items_to_search):
	result = '['
	for item in items_to_search:
		result += '{{"name":"{0}", "id":{1}}},'.format(escape(str(item)), item.id)
	result = result.rstrip(',') + ']'
	return mark_safe(result)

@register.simple_tag
def update_variable(value):
    """Allows to update existing variable in template"""
    return value

@register.simple_tag
def json_search_base_with_extra_fields(items_to_search, *extra_fields):
	"""
	This tag is similar to the json_search_base filter, but adds extra information upon request.
	The type of object is always provided in the JSON output. Thus, you have a heterogeneous collection
	of objects and differentiate them in your JavaScript. The extra fields are only added when an
	object actually has that attribute. Otherwise, the code skips over the request.
	"""
	result = '['
	for item in items_to_search:
		object_type = ContentType.objects.get_for_model(item).name
		result += '{{"name":"{0}", "id":{1}, "type":"{2}"'.format(escape(str(item)), item.id, object_type)
		for x in extra_fields:
			if hasattr(item, x):
				result += ', "{0}":"{1}"'.format(x, getattr(item, x))
		result += '},'
	result = result.rstrip(',') + ']'
	return mark_safe(result)


@register.simple_tag
def navigation_url(url_name, description):
	try:
		return format_html('<li><a href="{}">{}</a></li>', reverse(url_name), description)
	except NoReverseMatch:
		return ''


@register.filter
def get_item(dictionary, key):
	return dictionary.get(key)


dist_version: str = 0


@register.simple_tag
def app_version() -> str:
	global dist_version
	if dist_version != 0:
		return dist_version
	else:
		try:
			dist_version = get_distribution("NEMO").version
		except DistributionNotFound:
			# package is not installed
			dist_version = None
			pass
	return dist_version


@register.filter
def smooth_timedelta(timedeltaobj):
	"""Convert a datetime.timedelta object into Days, Hours, Minutes, Seconds."""
	if isinstance(timedeltaobj, str):
		return timedeltaobj
	secs = timedeltaobj.total_seconds()
	timetot = ""
	if secs > 86400: # 60sec * 60min * 24hrs
		days = secs // 86400
		timetot += "{} days".format(int(days))
		secs = secs - days*86400

	if secs > 3600:
		hrs = secs // 3600
		timetot += " {} hours".format(int(hrs))
		secs = secs - hrs*3600

	if secs > 60:
		mins = secs // 60
		timetot += " {} minutes".format(int(mins))
		secs = secs - mins*60

	if secs > 0:
		timetot += " {} seconds".format(int(secs))
	return timetot


@register.filter
def content_type(obj):
	if not obj:
		return False
	return ContentType.objects.get_for_model(obj)


@register.simple_tag
def get_content_data(work_order_transaction):
	user = work_order_transaction.work_order.customer
	content_object = work_order_transaction.content_object
	content_type = ContentType.objects.get_for_model(content_object)

	content_data = {}
	content_data["customer"] = user
	content_data["staff_member"] = None
	content_data["date_range"] = None
	content_data["project"] = None
	content_data["type"] = content_type.model
	content_data["item"] = None

	match content_type.model:
		case "usageevent":
			uep = UsageEventProject.objects.filter(usage_event=content_object, customer=user)
			if uep is not None:
				content_data["staff_member"] = content_object.operator
				content_data["item"] = content_object.tool
				content_data["project"] = uep[0].project
				content_data["date_range"] = format_datetime(content_object.start) + " - " + format_datetime(content_object.end)

		case "staffcharge":
			scp = StaffChargeProject.objects.filter(staff_charge=content_object, customer=user)
			if scp is not None:
				content_data["staff_member"] = content_object.staff_member
				content_data["item"] = content_object.staff_member
				content_data["project"] = scp[0].project
				content_data["date_range"] = format_datetime(content_object.start) + " - " + format_datetime(content_object.end)
		case "areaaccessrecord":
			aarp = AreaAccessRecordProject.objects.filter(area_access_record=content_object, customer=user)
			if aarp is not None:
				content_data["staff_member"] = content_object.user
				content_data["item"] = content_object.area
				content_data["project"] = aarp[0].project
				content_data["date_range"] = format_datetime(content_object.start) + " - " + format_datetime(content_object.end)
		case "consumablewithdraw":
			cw = content_object
			content_data["staff_member"] = content_object.merchant
			content_data["item"] = content_object.consumable
			content_data["project"] = cw.project
			content_data["date_range"] = format_datetime(content_object.date)

	return content_data


