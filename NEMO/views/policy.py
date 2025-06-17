from datetime import timedelta, datetime, date, time
from logging import getLogger

from django.core.mail import send_mail
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest
from django.template import Template, Context
from django.utils import timezone
from django.utils.dateparse import parse_time, parse_date, parse_datetime

from NEMO.models import Reservation, AreaAccessRecord, ScheduledOutage, PhysicalAccessLevel, Project, User, Tool, ProbationaryQualifications
from NEMO.utilities import format_datetime
from NEMO.views.customization import get_customization, get_media_file_contents

logger = getLogger(__name__)

def check_policy_to_enable_tool(tool, operator, user, project, staff_charge, request):
	"""
	Check that the user is allowed to enable the tool. Enable the tool if the policy checks pass.
	"""

	# The tool must be visible to users.
	if not tool.visible:
		return HttpResponseBadRequest("This tool is currently hidden from users.")

	# The tool must be operational.
	# If the tool is non-operational then it may only be accessed by staff members.
	if not tool.operational and not operator.is_staff:
		return HttpResponseBadRequest("This tool is currently non-operational.")

	# The tool must not be in use.
	current_usage_event = tool.get_current_usage_event()
	if current_usage_event:
		return HttpResponseBadRequest("The tool is currently being used by " + str(current_usage_event.user) + ".")

	# The user must be qualified to use the tool.
	if tool not in operator.qualifications.all() and not operator.is_staff:
		return HttpResponseBadRequest("You are not qualified to use this tool.")

	# Only staff members can operate a tool on behalf of another user.
	if (user and operator.pk != user.pk) and not operator.is_staff:
		return HttpResponseBadRequest("You must be a staff member to use a tool on another user's behalf.")

	# All required resources must be available to operate a tool except for staff.
	if tool.required_resource_set.filter(available=False).exists() and not operator.is_staff:
		return HttpResponseBadRequest("A resource that is required to operate this tool is unavailable.")

	# The tool operator may not activate tools in a particular area unless they are logged in to the area.
	# If they have access to the area, log them in automatically and let them know the log in to the area has occurrred
	if tool.requires_area_access and AreaAccessRecord.objects.filter(area=tool.requires_area_access,customer=operator,end=None, active_flag=True).count() == 0:
		if operator.physical_access_levels.filter(area=tool.requires_area_access).count() == 0 and not operator.is_staff:
			# return bad response that user doesn't have permission to the area
			return HttpResponseBadRequest("You don't have permission to be logged in to the {} to operate this tool.  Please contact a system administrator to request access.".format(tool.requires_area_access.name.lower()))


	# Staff may only charge staff time for one user at a time.
	if staff_charge and operator.charging_staff_time():
		return HttpResponseBadRequest('You are already charging staff time. You must end the current staff charge before you being another.')

	# Staff may not bill staff time to the themselves.
	if staff_charge and operator == user:
		return HttpResponseBadRequest('You cannot charge staff time to yourself.')

	# Users may only charge to projects they are members of.
	if project not in user.active_projects():
		return HttpResponseBadRequest('The user ' + str(user) + 'is not assigned to the project ' + str(project))

	# The tool operator must not have a lock on usage
	if operator.training_required:
		return HttpResponseBadRequest("You are blocked from using all tools in the laboratory. Please complete the laboratory rules tutorial in order to use tools.")

	if ProbationaryQualifications.objects.filter(tool=tool, user=operator, disabled=False).exists():
		# check if user is limited, and if they are running the tool within business hours
		if ProbationaryQualifications.objects.filter(tool=tool, user=operator, probationary_user=True).exists():
			business_start = time(8,0,0)
			#logger.error(str(business_start))
			business_end = time(17,0,0)
			#logger.error(str(business_end))
			current_time = timezone.now().time()
			#logger.error(str(current_time))
			intDay = timezone.now().weekday()
			#logger.error(str(intDay))
			if (intDay == 5 or intDay == 6 or current_time < business_start or current_time > business_end) and not operator.is_staff:
				td=timedelta(minutes=15)
				if not Reservation.objects.filter(start__lt=timezone.now()+td, end__gt=timezone.now(), cancelled=False, missed=False, shortened=False, user=operator, tool=tool).exists():
					return HttpResponseBadRequest("You are a limited user of the {}.  You may only operate the tool during normal business hours of 8 am to 5 pm Monday - Friday.".format(tool.name))

	# Users may only use a tool when delayed logoff is not in effect. Staff are exempt from this rule.
	if tool.delayed_logoff_in_progress() and not operator.is_staff:
		return HttpResponseBadRequest("Delayed tool logoff is in effect. You must wait for the delayed logoff to expire before you can use the tool.")

	# Users may not enable a tool during a scheduled outage. Staff are exempt from this rule.
	if tool.scheduled_outage_in_progress() and not operator.is_staff:
		return HttpResponseBadRequest("A scheduled outage is in effect. You must wait for the outage to end before you can use the tool.")

	# Refuses login on tools that require reservations if there is no reservation
	if tool.reservation_required and not operator.is_staff:
		td=timedelta(minutes=15)
		if not Reservation.objects.filter(start__lt=timezone.now()+td, end__gt=timezone.now(), cancelled=False, missed=False, shortened=False, user=operator, tool=tool).exists():
			return HttpResponseBadRequest("A reservation is required to enable this tool.")

	# Prevent tool login for user from a different core
	active_core_id = request.session.get("active_core_id")
	if str(active_core_id) != "0" and str(active_core_id) != "None":
		msg = "The " + tool.name + " is part of the core " + tool.core_id.name + ". You cannot operate a tool that is part of a different core."
		if str(tool.core_id.id) not in str(active_core_id) and tool not in operator.qualifications.all() and not operator.is_superuser:
			return HttpResponseBadRequest(msg)


	return HttpResponse()


def check_policy_to_enable_tool_for_multi(tool, operator, user, project, request):
	"""
	Check that the user is allowed to enable the tool. Enable the tool if the policy checks pass.
	"""

	# The tool must be visible to users.
	if not tool.visible:
		return HttpResponseBadRequest("This tool is currently hidden from users.")

	# The tool must be operational.
	# If the tool is non-operational then it may only be accessed by staff members.
	if not tool.operational and not operator.is_staff:
		return HttpResponseBadRequest("This tool is currently non-operational.")

	# The user must be qualified to use the tool.
	if tool not in operator.qualifications.all() and not operator.is_staff:
		return HttpResponseBadRequest("You are not qualified to use this tool.")

	# Only staff members can operate a tool on behalf of another user.
	if (user and operator.pk != user.pk) and not operator.is_staff:
		return HttpResponseBadRequest("You must be a staff member to use a tool on another user's behalf.")

	# All required resources must be available to operate a tool except for staff.
	if tool.required_resource_set.filter(available=False).exists() and not operator.is_staff:
		return HttpResponseBadRequest("A resource that is required to operate this tool is unavailable.")

	# The tool operator may not activate tools in a particular area unless they are logged in to the area.
	# If they have access to the area, log them in automatically and let them know the log in to the area has occurrred
	if tool.requires_area_access and AreaAccessRecord.objects.filter(area=tool.requires_area_access,customer=operator,end=None, active_flag=True).count() == 0:
		if operator.physical_access_levels.filter(area=tool.requires_area_access).count() == 0 and not operator.is_staff:
			# return bad response that user doesn't have permission to the area
			return HttpResponseBadRequest("You don't have permission to be logged in to the {} to operate this tool.  Please contact a system administrator to request access.".format(tool.requires_area_access.name.lower()))


	# Users may only charge to projects they are members of.
	if project not in user.active_projects():
		return HttpResponseBadRequest('The user ' + str(user) + ' is not assigned to the project ' + str(project))

	# The tool operator must not have a lock on usage
	if operator.training_required:
		return HttpResponseBadRequest("You are blocked from using all tools in the laboratory. Please complete the laboratory rules tutorial in order to use tools.")

	# Users may only use a tool when delayed logoff is not in effect. Staff are exempt from this rule.
	if tool.delayed_logoff_in_progress() and not operator.is_staff:
		return HttpResponseBadRequest("Delayed tool logoff is in effect. You must wait for the delayed logoff to expire before you can use the tool.")

	# Users may not enable a tool during a scheduled outage. Staff are exempt from this rule.
	if tool.scheduled_outage_in_progress() and not operator.is_staff:
		return HttpResponseBadRequest("A scheduled outage is in effect. You must wait for the outage to end before you can use the tool.")

	# Refuses login on tools that require reservations if there is no reservation
	if tool.reservation_required and not operator.is_staff:
		td=timedelta(minutes=15)
		if not Reservation.objects.filter(start__lt=timezone.now()+td, end__gt=timezone.now(), cancelled=False, missed=False, shortened=False, user=operator, tool=tool).exists():
			return HttpResponseBadRequest("A reservation is required to enable this tool.")

	# Prevent tool login for user from a different core
	active_core_id = request.session.get("active_core_id")
	if str(active_core_id) != "0" and str(active_core_id) != "None":
		msg = "The " + tool.name + " is part of the core " + tool.core_id.name + ". You cannot operate a tool that is part of a different core."
		if str(tool.core_id.id) not in str(active_core_id) and tool not in operator.qualifications.all() and not operator.is_superuser:
			return HttpResponseBadRequest(msg)


	return HttpResponse()


def check_policy_to_disable_tool(tool, operator, downtime, request):
	# Prevent tool disabling from a user in a different core
	active_core_id = request.session.get("active_core_id")
	if str(active_core_id) != "0" and str(active_core_id) != "None":
		if str(tool.core_id.id) not in str(active_core_id) and tool not in operator.qualifications.all() and not operator.is_superuser:
			return HttpResponseBadRequest("You cannot disable a tool that is part of a different Core.")

	""" Check that the user is allowed to disable the tool. """
	current_usage_event = tool.get_current_usage_event()
	if current_usage_event.operator != operator and current_usage_event.user != operator and not operator.is_staff:
		return HttpResponseBadRequest('You may not disable a tool while another user is using it unless you are a staff member.')

	if downtime < timedelta():
		return HttpResponseBadRequest('Downtime cannot be negative.')

	if downtime > timedelta(minutes=120):
		return HttpResponseBadRequest('Post-usage tool downtime may not exceed 120 minutes.')

	if tool.delayed_logoff_in_progress() and downtime > timedelta():
		return HttpResponseBadRequest('The tool is already in a delayed-logoff state. You may not issue additional delayed logoffs until the existing one expires.')

	if not tool.allow_delayed_logoff and downtime > timedelta():
		return HttpResponseBadRequest('Delayed logoff is not allowed for this tool.')

	return HttpResponse()


def check_policy_to_save_reservation(request, cancelled_reservation, new_reservation, user, explicit_policy_override):
	""" Check the reservation creation policy and return a list of policy problems """

	# The function will check all policies. Policy problems are placed in the policy_problems list. overridable is True if the policy problems can be overridden by a staff member.
	policy_problems = []
	overridable = False

	new_reservation_start = parse_datetime(str(new_reservation.start))
	new_reservation_start = new_reservation_start.astimezone(timezone.get_current_timezone())
	new_reservation_end = parse_datetime(str(new_reservation.end))
	new_reservation_end = new_reservation_end.astimezone(timezone.get_current_timezone())

	# Reservations may not have a start time that is earlier than the end time.
	if new_reservation_start >= new_reservation_end:
		policy_problems.append("Reservation start time (" + str(new_reservation_start) + ") must be before the end time (" + str(new_reservation_end) + ").")

	# The user may not create, move, or resize a reservation to coincide with another user's reservation.
	coincident_events = Reservation.objects.filter(tool=new_reservation.tool, cancelled=False, missed=False, shortened=False)
	# Exclude the reservation we're cancelling in order to create a new one:
	if cancelled_reservation and cancelled_reservation.id:
		coincident_events = coincident_events.exclude(id=cancelled_reservation.id)
	# Exclude events for which the following is true:
	# The event starts and ends before the time-window, and...
	# The event starts and ends after the time-window.
	coincident_events = coincident_events.exclude(start__lt=new_reservation_start, end__lte=new_reservation_start)
	coincident_events = coincident_events.exclude(start__gte=new_reservation_end, end__gt=new_reservation_end)

	# since the creation process an be recursive we should check if our new reservation is really an update, and exclude it if it has an id, since an actual new_reservation should have a null id
	if new_reservation.id is not None:
		coincident_events = coincident_events.exclude(id=new_reservation.id)

	if coincident_events.count() > 0:
		policy_problems.append("Your reservation coincides with another reservation that already exists. Please choose a different time.")

	# The user may not create, move, or resize a reservation to coincide with a scheduled outage.
	coincident_events = ScheduledOutage.objects.filter(Q(tool=new_reservation.tool) | Q(resource__fully_dependent_tools__in=[new_reservation.tool]))
	# Exclude events for which the following is true:
	# The event starts and ends before the time-window, and...
	# The event starts and ends after the time-window.
	coincident_events = coincident_events.exclude(start__lt=new_reservation_start, end__lte=new_reservation_start)
	coincident_events = coincident_events.exclude(start__gte=new_reservation_end, end__gt=new_reservation_end)
	if coincident_events.count() > 0:
		policy_problems.append("Your reservation coincides with a scheduled outage. Please choose a different time.")

	# Reservations that have been cancelled may not be changed.
	if new_reservation.cancelled:
		policy_problems.append("This reservation has already been cancelled by " + str(new_reservation.cancelled_by) + " at " + format_datetime(new_reservation.cancellation_time) + ".")

	# The user must belong to at least one active project to make a reservation.
	if new_reservation.user.active_project_count() < 1:
		if new_reservation.user == user:
			policy_problems.append("You do not belong to any active projects. Thus, you may not create any reservations.")
		else:
			policy_problems.append(str(new_reservation.user) + " does not belong to any active projects and cannot have reservations.")

	# The user must associate their reservation with a project they belong to.
	if new_reservation.project and new_reservation.project not in new_reservation.user.active_projects():
		if new_reservation.user == user:
			policy_problems.append("You do not belong to the project associated with this reservation.")
		else:
			policy_problems.append(str(new_reservation.user) + " does not belong to the project named " + str(new_reservation.project) + ".")

#	# Check that a staff member is part of the core to which tool belongs
	if user.is_staff:
		active_core_id = list(user.core_ids.values_list('id', flat=True))
	else:
		active_core_id = request.session.get("active_core_id")
		
	if str(new_reservation.tool.core_id.id) not in str(active_core_id) and new_reservation.tool not in user.qualifications.all() and not user.is_superuser:
			msg = "Your core is not the same as the core of " + str(new_reservation.tool.core_id.name) + " to which the " + str(new_reservation.tool.name) + " belongs.  You cannot make a reservation for this tool."
			policy_problems.append(msg)

	# If the user is a staff member or there's an explicit policy override then the policy check is finished.
	if user.is_staff or explicit_policy_override:
		return policy_problems, overridable

	# If there are no blocking policy conflicts at this point, the rest of the policies can be overridden.
	if not policy_problems:
		overridable = True

	# The user must complete NEMO training to create reservations.
	# Staff may break this rule.
	# An explicit policy override allows this rule to be broken.
	if user.training_required:
		policy_problems.append("You are blocked from making reservations for all tools in the laboratory. Please complete the laboratory rules tutorial in order to create new reservations.")

	# Users may only change their own reservations.
	# Staff may break this rule.
	# An explicit policy override allows this rule to be broken.
	if new_reservation.user != user:
		policy_problems.append("You may not change reservations that you do not own.")

	# The user may not create or move a reservation to have a start time that is earlier than the current time.
	# Staff may break this rule.
	# An explicit policy override allows this rule to be broken.
	if new_reservation_start < timezone.now():
		policy_problems.append("Reservation start time (" + str(new_reservation_start) + ") is earlier than the current time (" + format_datetime(timezone.now()) + ").")

	# The user may not move or resize a reservation to have an end time that is earlier than the current time.
	# Staff may break this rule.
	# An explicit policy override allows this rule to be broken.
	if new_reservation_end < timezone.now():
		policy_problems.append("Reservation end time (" + str(new_reservation_end) + ") is earlier than the current time (" + format_datetime(timezone.now()) + ").")

	# The user must be qualified on the tool in question in order to create, move, or resize a reservation.
	# Staff may break this rule.
	# An explicit policy override allows this rule to be broken.
	if new_reservation.tool not in user.qualifications.all():
		policy_problems.append("You are not qualified to use this tool. Creating, moving, and resizing reservations is forbidden.")

	# probationary users may only reserve a tool during regular business hours
	if ProbationaryQualifications.objects.filter(tool=new_reservation.tool, user=user).exists():
		# check if user is probationary, and if they are running the tool within business hours
		if ProbationaryQualifications.objects.filter(tool=new_reservation.tool, user=user, probationary_user=True).exists():
			business_start = time(8,0,0)
			#logger.error(str(business_start))
			business_end = time(17,0,0)
			#logger.error(str(business_end))
			intDay = new_reservation_start.weekday()
			#logger.error(str(intDay))
			if (intDay == 5 or intDay == 6 or new_reservation_start.time() < business_start or new_reservation_start.time() > business_end or new_reservation_end.time() < business_start or new_reservation_end.time() > business_end) and not user.is_staff:
				policy_problems.append("You are a limited user of the {}.  You may only reserve the tool for times during normal business hours of 8 am to 5 pm Monday - Friday.".format(new_reservation.tool.name))

	# The reservation start time may not exceed the tool's reservation horizon.
	# Staff may break this rule.
	# An explicit policy override allows this rule to be broken.
	if new_reservation.tool.reservation_horizon is not None:
		reservation_horizon = timedelta(days=new_reservation.tool.reservation_horizon)
		if new_reservation_start > timezone.now() + reservation_horizon:
			policy_problems.append("You may not create reservations further than " + str(reservation_horizon.days) + " days from now for this tool.")

	# Calculate the duration of the reservation:
	duration = new_reservation_end - new_reservation_start

	# The reservation must be at least as long as the minimum block time for this tool.
	# Staff may break this rule.
	# An explicit policy override allows this rule to be broken.
	if new_reservation.tool.minimum_usage_block_time:
		minimum_block_time = timedelta(minutes=new_reservation.tool.minimum_usage_block_time)
		if duration < minimum_block_time:
			policy_problems.append("Your reservation has a duration of " + str(int(duration.total_seconds() / 60)) + " minutes. This tool requires a minimum reservation duration of " + str(int(minimum_block_time.total_seconds() / 60)) + " minutes.")

	# The reservation may not exceed the maximum block time for this tool.
	# Staff may break this rule.
	# An explicit policy override allows this rule to be broken.
	if new_reservation.tool.maximum_usage_block_time:
		maximum_block_time = timedelta(minutes=new_reservation.tool.maximum_usage_block_time)
		if duration > maximum_block_time:
			policy_problems.append("Your reservation has a duration of " + str(int(duration.total_seconds() / 60)) + " minutes. Reservations for this tool may not exceed " + str(int(maximum_block_time.total_seconds() / 60)) + " minutes.")

	# If there is a limit on number of reservations per user per day then verify that the user has not exceeded it.
	# Staff may break this rule.
	# An explicit policy override allows this rule to be broken.
	if new_reservation.tool.maximum_reservations_per_day:
		start_of_day = new_reservation_start
		#logger.error(str(start_of_day))
		start_of_day = start_of_day.replace(hour=0, minute=0, second=0, microsecond=0)
		#logger.error(str(start_of_day))
		end_of_day = start_of_day + timedelta(days=1)
		#logger.error(str(end_of_day))
		reservations_for_that_day = Reservation.objects.filter(cancelled=False, shortened=False, start__gte=start_of_day, end__lte=end_of_day, user=user, tool=new_reservation.tool)
		# Exclude any reservation that is being cancelled.
		if cancelled_reservation and cancelled_reservation.id:
			reservations_for_that_day = reservations_for_that_day.exclude(id=cancelled_reservation.id)
		if reservations_for_that_day.count() >= new_reservation.tool.maximum_reservations_per_day:
			policy_problems.append("You may only have " + str(new_reservation.tool.maximum_reservations_per_day) + " reservations for this tool per day. Missed reservations are included when counting the number of reservations per day.")

	# A minimum amount of time between reservations for the same user & same tool can be enforced.
	# Staff may break this rule.
	# An explicit policy override allows this rule to be broken.
	if new_reservation.tool.minimum_time_between_reservations:
		buffer_time = timedelta(minutes=new_reservation.tool.minimum_time_between_reservations)
		must_end_before = new_reservation_start - buffer_time
		#logger.error(str(must_end_before))
		too_close = Reservation.objects.filter(cancelled=False, missed=False, shortened=False, user=user, end__gt=must_end_before, start__lt=new_reservation_start, tool=new_reservation.tool)
		if cancelled_reservation and cancelled_reservation.id:
			too_close = too_close.exclude(id=cancelled_reservation.id)
		if too_close.exists():
			policy_problems.append("Separate reservations for this tool that belong to you must be at least " + str(new_reservation.tool.minimum_time_between_reservations) + " minutes apart from each other. The proposed reservation ends too close to another reservation.")
		must_start_after = new_reservation.end + buffer_time
		#logger.error(str(must_start_after))
		too_close = Reservation.objects.filter(cancelled=False, missed=False, shortened=False, user=user, start__lt=must_start_after, end__gt=new_reservation_start, tool=new_reservation.tool)
		if cancelled_reservation and cancelled_reservation.id:
			too_close = too_close.exclude(id=cancelled_reservation.id)
		if too_close.exists():
			policy_problems.append("Separate reservations for this tool that belong to you must be at least " + str(new_reservation.tool.minimum_time_between_reservations) + " minutes apart from each other. The proposed reservation begins too close to another reservation.")

	# Check that the user is not exceeding the maximum amount of time they may reserve in the future.
	# Staff may break this rule.
	# An explicit policy override allows this rule to be broken.
	if new_reservation.tool.maximum_future_reservation_time:
		reservations_after_now = Reservation.objects.filter(cancelled=False, user=user, tool=new_reservation.tool, start__gte=timezone.now())
		if cancelled_reservation and cancelled_reservation.id:
			reservations_after_now = reservations_after_now.exclude(id=cancelled_reservation.id)
		amount_reserved_in_the_future = new_reservation.duration()
		for r in reservations_after_now:
			amount_reserved_in_the_future += r.duration()
		if amount_reserved_in_the_future.total_seconds() / 60 > new_reservation.tool.maximum_future_reservation_time:
			policy_problems.append("You may only reserve up to " + str(new_reservation.tool.maximum_future_reservation_time) + " minutes of time on this tool, starting from the current time onward.")

	# Return the list of all policies that are not met.
	return policy_problems, overridable


def check_policy_to_cancel_reservation(reservation, user, request):
	"""
	Checks the reservation deletion policy.
	If all checks pass the function returns an HTTP "OK" response.
	Otherwise, the function returns an HTTP "Bad Request" with an error message.
	"""

	# Users may only cancel reservations that they own.
	# Staff may break this rule.
	if (reservation.user != user) and not user.is_staff:
		return HttpResponseBadRequest("You may not cancel reservations that you do not own.")

	# Users may not cancel reservations that have already ended.
	# Staff may break this rule.
	if reservation.end < timezone.now(): # and not user.is_staff:
		return HttpResponseBadRequest("You may not cancel reservations that have already ended.")

	if reservation.cancelled:
		return HttpResponseBadRequest("This reservation has already been cancelled by " + str(reservation.cancelled_by) + " at " + format_datetime(reservation.cancellation_time) + ".")

	if reservation.missed:
		return HttpResponseBadRequest("This reservation was missed and cannot be modified.")

	# Staff may only cancel reservations for tools in their core
	active_core_id = request.session.get("active_core_id")
	if str(active_core_id) != "0" and str(active_core_id) != "None":
		if str(reservation.tool.core_id.id) not in str(active_core_id) and reservation.tool not in user.qualifications.all() and not user.is_superuser:
			msg = "Your core is not the same as the core of " + str(reservation.tool.core_id.name) + " to which the " + str(reservation.tool.name) + " belongs.  You cannot cancel a reservation for this tool."
			return HttpResponseBadRequest(msg)

	return HttpResponse()


def check_policy_to_create_outage(outage, request):
	# Outages may not have a start time that is earlier than the end time.
	if outage.start >= outage.end:
		return "Outage start time (" + format_datetime(outage.start) + ") must be before the end time (" + format_datetime(outage.end) + ")."

	# The user may not create, move, or resize an outage to coincide with another user's reservation.
	coincident_events = Reservation.objects.filter(tool=outage.tool, cancelled=False, missed=False, shortened=False)
	# Exclude events for which the following is true:
	# The event starts and ends before the time-window, and...
	# The event starts and ends after the time-window.
	coincident_events = coincident_events.exclude(start__lt=outage.start, end__lte=outage.start)
	coincident_events = coincident_events.exclude(start__gte=outage.end, end__gt=outage.end)
	if coincident_events.count() > 0:
		return "Your scheduled outage coincides with a reservation that already exists. Please choose a different time."

	# prevent staff from creating outages on tools in different cores
	active_core_id = request.session.get("active_core_id")
	if str(active_core_id) != "0" and str(active_core_id) != "None":
		if str(outage.tool.core_id.id) not in str(active_core_id) and outage.tool not in request.user.qualifications.all() and not request.user.is_superuser:
			msg = "Your core is not the same as the core of " + str(outage.tool.core_id.name) + " to which the " + str(outage.tool.name) + " belongs.  You cannot create an outage for this tool."
			return HttpResponseBadRequest(msg)

	# No policy issues! The outage can be created...
	return None
