import io
from collections import defaultdict
from datetime import timedelta
from http import HTTPStatus
from logging import getLogger
from re import match, search

import requests
import datetime
from icalendar import Calendar, Event
from dateutil.rrule import rrulestr
from dateutil.tz import gettz, UTC
from icalendar.prop import vDDDLists

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.postgres.aggregates import ArrayAgg
from django.core.mail import send_mail, EmailMessage
from django.db.models import F, Q, CharField, Value
from django.db.models.functions import Concat
from django.http import HttpResponseBadRequest, HttpResponse, HttpResponseNotFound, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404, redirect
from django.template import Template, Context
from django.utils import timezone, dateformat
from django.views.decorators.http import require_GET, require_POST
from django.utils.html import escape
from django.utils.safestring import mark_safe

from NEMO.decorators import disable_session_expiry_refresh
from NEMO.forms import MultiCalendarForm, ToolDurationFormSet
from NEMO.models import Tool, Reservation, Configuration, ReservationConfiguration, ReservationProject, ReservationNotification, Consumable, UsageEvent, UsageEventProject, AreaAccessRecord, StaffCharge, StaffChargeProject, User, Project, ScheduledOutage, ScheduledOutageCategory, UserProfile, UserProfileSetting, Sample
from NEMO.utilities import EmailCategory, create_email_log, bootstrap_primary_color, create_email_attachment, extract_times, extract_dates, format_datetime, parse_parameter_string
from NEMO.views.constants import ADDITIONAL_INFORMATION_MAXIMUM_LENGTH
from NEMO.views.customization import get_customization, get_media_file_contents
from NEMO.views.policy import check_policy_to_save_reservation, check_policy_to_cancel_reservation, check_policy_to_create_outage
from NEMO.widgets.tool_tree import ToolTree


@login_required
@require_GET
def calendar(request, tool_id=None, qualified_only=None, core_only=None):
	""" Present the calendar view to the user. """
	
	if request.device == 'mobile':
		if tool_id and int(tool_id) > 0:
			return redirect('view_calendar', tool_id)
		else:
			return redirect('choose_tool', 'view_calendar')


	tools = Tool.objects.filter(visible=True).order_by('category', 'name')
	ctools = Tool.objects.filter(visible=True).order_by('category', 'name')

	if qualified_only is not None:
		if int(qualified_only) == 1:
			tools = tools.filter(id__in=request.user.qualifications.all()).order_by('category', 'name')
			ctools = ctools.filter(id__in=request.user.qualifications.all()).order_by('category', 'name')

	if core_only is not None:
		if int(core_only) == 1:
			tools = tools.filter(Q(core_id__in=request.user.core_ids.all()) | Q(id__in=request.user.qualifications.all())).order_by('category', 'name')
			ctools = ctools.filter(Q(core_id__in=request.user.core_ids.all()) | Q(id__in=request.user.qualifications.all())).order_by('category', 'name')

	# create searchable names for tools that include the category
	categorized_tools = "["
	for t in ctools:
		categorized_tools += '{{"name":"{0}", "id":{1}}},'.format(escape(str(t.category))+"/"+escape(str(t.name)), t.id)
	categorized_tools = categorized_tools.rstrip(",") + "]"
	categorized_tools = mark_safe(categorized_tools)

	rendered_tool_tree_html = ToolTree().render(None, {'tools': tools})

	if tool_id is None:
		tool_id = 0

	dictionary = {
		'rendered_tool_tree_html': rendered_tool_tree_html,
		'tools': tools,
		'auto_select_tool': tool_id,
		'qualified_only': qualified_only,
		'core_only': core_only,
		'cat_tools': categorized_tools,
	}

	if request.user.is_staff:
		dictionary['users'] = User.objects.filter(is_active=True, projects__active=True).exclude(id=request.user.id).distinct().order_by('last_name')

	return render(request, 'calendar/calendar.html', dictionary)


@login_required
@require_GET
@disable_session_expiry_refresh
def event_feed(request):
	""" Get all reservations for a specific time-window. Optionally: filter by tool or user name. """
	try:
		start, end = extract_dates(request.GET)
	except Exception as e:
		return HttpResponseBadRequest('Invalid start or end time. ' + str(e))

	# We don't want to let someone hammer the database with phony calendar feed lookups.
	# Block any requests that have a duration of more than 8 weeks. The FullCalendar
	# should only ever request 6 weeks of data at a time (at most).
	if end - start > timedelta(weeks=8):
		return HttpResponseBadRequest("Calendar feed request has too long a duration: " + str(end - start))

	event_type = request.GET.get('event_type')

	if event_type == 'reservations':
		return reservation_event_feed(request, start, end)
	elif event_type == 'laboratory usage':
		return usage_event_feed(request, start, end)
	# Only staff may request a specific user's history...
	elif event_type == 'specific user' and request.user.is_staff:
		user = get_object_or_404(User, id=request.GET.get('user'))
		return specific_user_feed(request, user, start, end)
	elif event_type == 'multi-tool display':
		return multiple_tool_feed(request, start, end)
	else:
		return HttpResponseBadRequest('Invalid event type or operation not authorized.')


def multiple_tool_feed(request, start, end):
	events = Reservation.objects.filter(cancelled=False, missed=False, shortened=False)
	outages = None
	# Exclude events for which the following is true:
	# The event starts and ends before the time-window, and...
	# The event starts and ends after the time-window.
	events = events.exclude(start__lt=start, end__lt=start)
	events = events.exclude(start__gt=end, end__gt=end)

	# Filter events that only have to do with the relevant tool.
	tools = request.GET.get('tool_ids')
	tool_list = tools.split(",")

	if len(tool_list) > 0:
		events = events.filter(tool__id__in=tool_list)

		outages = ScheduledOutage.objects.filter(tool_id__in=tool_list)
		outages = outages.exclude(start__lt=start, end__lt=start)
		outages = outages.exclude(start__gt=end, end__gt=end)
	else:
		events = None

	event_data = {}

	if events is not None:
		event_projects = ReservationProject.objects.filter(reservation__in=events)
		event_notifications = ReservationNotification.objects.filter(reservation__in=events, user=request.user)

		for e in events:
			event_data[e.id] = {
				'id': e.id,
				'start': e.start,
				'end': e.end,
				'description': e.description,
				'user': e.user,
				'tool': e.tool,
				'creator': e.creator,
				'additional_information': e.additional_information,
				'title': e.title,
				'get_visual_end': e.get_visual_end(),
				'mark_for_notice': ReservationNotification.objects.filter(user=request.user, reservation=e).exists(),
			}
	else:
		event_projects = None
		event_notifications = None
		event_data = None

	dictionary = {
		'events': event_data,
		'event_projects': event_projects,
		'event_notifications': event_notifications,
		'outages': outages,
	}

	return render(request, 'calendar/multi_tool_event_feed.html', dictionary)


def reservation_event_feed(request, start, end):
	events = Reservation.objects.filter(cancelled=False, missed=False, shortened=False)
	outages = None
	current = None

	# Exclude events for which the following is true:
	# The event starts and ends before the time-window, and...
	# The event starts and ends after the time-window.
	events = events.exclude(start__lt=start, end__lt=start)
	events = events.exclude(start__gt=end, end__gt=end)

	# Filter events that only have to do with the relevant tool.
	tool = request.GET.get('tool_id')
	personal_schedule = request.GET.get('personal_schedule')
	if tool:
		ps_events = events.filter(user=request.user)
		ps_events = ps_events.exclude(tool__id=tool)

		ps_overlay = request.GET.get('ps_overlay')
		if ps_overlay == '0' or ps_overlay is None:
			ps_events = None

		events = events.filter(tool__id=tool)

		outages = ScheduledOutage.objects.filter(Q(tool=tool) | Q(resource__fully_dependent_tools__in=[tool]))
		outages = outages.exclude(start__lt=start, end__lt=start)
		outages = outages.exclude(start__gt=end, end__gt=end)

		current = UsageEvent.objects.filter(tool=tool)
		current = current.exclude(start__lt=start, end__lt=start)
		current = current.exclude(start__gt=end, end__gt=end)

	# Filter events that only have to do with the current user.
	if personal_schedule:
		ps_events = None
		events = events.filter(user=request.user)

	if not tool and not personal_schedule:
		events = None

	if events is not None:
		event_projects = ReservationProject.objects.filter(reservation__in=events)
	else:
		event_projects = None

	#events = events.annotate(long_description=Concat(Value('<p>TEST - '), 'user_id', Value('</p>'), output_field=CharField()))

	dictionary = {
		'events': events,
		'event_projects': event_projects,
		'outages': outages,
		'personal_schedule': personal_schedule,
		'current': current,
		'current_time': timezone.now(),
		'ps_events': ps_events,
		'noteshtml': "<span class='glyphicon glyphicon-list-alt'></span><br/>",
	}
	return render(request, 'calendar/reservation_event_feed.html', dictionary)


def usage_event_feed(request, start, end):
	usage_events = UsageEvent.objects.filter(active_flag=True)
	# Exclude events for which the following is true:
	# The event starts and ends before the time-window, and...
	# The event starts and ends after the time-window.
	usage_events = usage_events.exclude(start__lt=start, end__lt=start)
	usage_events = usage_events.exclude(start__gt=end, end__gt=end)

	# Filter events that only have to do with the relevant tool.
	tool = request.GET.get('tool_id')
	if tool:
		usage_events = usage_events.filter(tool__id=tool)

	area_access_events = None
	# Filter events that only have to do with the current user.
	personal_schedule = request.GET.get('personal_schedule')
	if personal_schedule:
		usage_events = usage_events.filter(user=request.user)
		# Display area access along side tool usage when 'personal schedule' is selected.
		area_access_events = AreaAccessRecord.objects.filter(customer__id=request.user.id, active_flag=True)
		area_access_events = area_access_events.exclude(start__lt=start, end__lt=start)
		area_access_events = area_access_events.exclude(start__gt=end, end__gt=end)

	missed_reservations = None
	if personal_schedule:
		missed_reservations = Reservation.objects.filter(missed=True, user=request.user)
	elif tool:
		missed_reservations = Reservation.objects.filter(missed=True, tool=tool)
	if missed_reservations:
		missed_reservations = missed_reservations.exclude(start__lt=start, end__lt=start)
		missed_reservations = missed_reservations.exclude(start__gt=end, end__gt=end)

	if usage_events is not None:
		usage_event_projects = UsageEventProject.objects.filter(usage_event__in=usage_events, active_flag=True)
	else:
		usage_event_projects = None

	if missed_reservations is not None:
		missed_reservation_projects = ReservationProject.objects.filter(reservation__in=missed_reservations)
	else:
		missed_reservation_projects = None

	dictionary = {
		'usage_events': usage_events,
		'usage_event_projects': usage_event_projects,
		'area_access_events': area_access_events,
		'personal_schedule': personal_schedule,
		'missed_reservations': missed_reservations,
		'missed_reservation_projects': missed_reservation_projects,
	}
	return render(request, 'calendar/usage_event_feed.html', dictionary)


def specific_user_feed(request, user, start, end):
	# Find all tool usage events for a user.
	# Exclude events for which the following is true:
	# The event starts and ends before the time-window, and...
	# The event starts and ends after the time-window.
	usage_events = UsageEvent.objects.filter(user=user, active_flag=True)
	usage_events = usage_events.exclude(start__lt=start, end__lt=start)
	usage_events = usage_events.exclude(start__gt=end, end__gt=end)

	# Find all area access events for a user.
	area_access_events = AreaAccessRecord.objects.filter(customer=user, active_flag=True)
	area_access_events = area_access_events.exclude(start__lt=start, end__lt=start)
	area_access_events = area_access_events.exclude(start__gt=end, end__gt=end)

	# Find all reservations for the user that were not missed or cancelled.
	reservations = Reservation.objects.filter(user=user, missed=False, cancelled=False, shortened=False)
	reservations = reservations.exclude(start__lt=start, end__lt=start)
	reservations = reservations.exclude(start__gt=end, end__gt=end)

	# Find all missed reservations for the user.
	missed_reservations = Reservation.objects.filter(user=user, missed=True)
	missed_reservations = missed_reservations.exclude(start__lt=start, end__lt=start)
	missed_reservations = missed_reservations.exclude(start__gt=end, end__gt=end)

	dictionary = {
		'usage_events': usage_events,
		'area_access_events': area_access_events,
		'reservations': reservations,
		'missed_reservations': missed_reservations,
	}
	return render(request, 'calendar/specific_user_feed.html', dictionary)


@login_required
@require_POST
def create_reservation(request):
	logger = getLogger(__name__)

	""" Create a reservation for a user. """
	try:
		start, end = extract_times(request.POST)
	except Exception as e:
		logger.exception(str(e))
		return HttpResponseBadRequest(str(e))
	tool = get_object_or_404(Tool, name=request.POST.get('tool_name'))
	explicit_policy_override = False

	reservation_projects = None
	sample_selections = None

	if request.user.is_staff:
		try:
			user = User.objects.get(id=request.POST['impersonate'])
		except:
			user = request.user
		try:
			explicit_policy_override = request.POST['explicit_policy_override'] == 'true'
		except Exception as e:
			#logger.exception(str(e))
			pass
	else:
		user = request.user

	b_send_mail = False
	mail_setting = UserProfileSetting.objects.get(name="RESERVATION_CALENDAR_INVITES")

	if UserProfile.objects.filter(user=user, setting=mail_setting).exists():
		setting = UserProfile.objects.get(user=user, setting=mail_setting)
		b_send_mail = bool(int(setting.value))


	# check if this is an update to a new reservation, specifically for the case of a reservation for a configurable tool
	if request.POST.get('reservation_id') is not None:
		try:
			new_reservation = Reservation.objects.get(id=int(request.POST.get('reservation_id')))
		except Exception as e:
			logger.exception(str(e))
	else:
		# Create the new reservation:
		new_reservation = Reservation()
		new_reservation.created = timezone.now()
		new_reservation.user = user
		new_reservation.creator = request.user
		new_reservation.tool = tool
		new_reservation.start = start
		new_reservation.end = end
		new_reservation.short_notice = determine_insufficient_notice(tool, start)

	policy_problems, overridable = check_policy_to_save_reservation(request, None, new_reservation, user, explicit_policy_override)

	# If there was a problem in saving the reservation then return the error...
	if policy_problems:
		return render(request, 'calendar/policy_dialog.html', {'policy_problems': policy_problems, 'overridable': overridable and request.user.is_staff})

	# All policy checks have passed.


	if not user.is_staff:

		# If the user only has one project then associate it with the reservation.
		# Otherwise, present a dialog box for the user to choose which project to associate.
		active_projects = user.active_projects()
		#if len(active_projects) == 1:
		#	new_reservation.project = active_projects[0]
			
		#else:
		try:
			new_reservation.project = Project.objects.get(id=request.POST['project_id'])
		except:
			return render(request, 'calendar/project_choice.html', {'active_projects': active_projects})
	
		# Make sure the user is actually enrolled on the project. We wouldn't want someone
		# forging a request to reserve against a project they don't belong to.
		if new_reservation.project not in new_reservation.user.active_projects():
			return render(request, 'calendar/project_choice.html', {'active_projects': active_projects()})

	else:

		user_2dcc = False

		if "2DCC" in request.user.core_ids.values_list('name', flat=True):
			user_2dcc = True

		# Present the staff member with a form to choose if the reservation is for themselves for or one or more customers.
		if request.POST.get('staff_charge') is None:
			#users = User.objects.filter(is_active=True, projects__active=True).exclude(id=request.user.id).annotate(project_number=ArrayAgg('projects2dcc__project_id', distinct=True)).distinct().order_by('last_name')
			users = User.objects.filter(is_active=True, projects__active=True).exclude(id=request.user.id).annotate(project_number=F('projects2dcc__project_id')).distinct().order_by('last_name')

			#if user_2dcc and request.user.core_ids.all().count() == 1:
				#users = users.filter(is_staff=False, projects2dcc__in=request.user.projects2dcc.all())
			
			return render(request, 'calendar/project_choice_staff.html', { 'active_projects': user.active_projects(), 'users': users, 'user_2dcc': user_2dcc})
		else:
			# process submission to determine the reservation details
			mode = request.POST['staff_charge']

			if mode == "self":
				# make a reservation for the user and don't add a record to the ReservationProject table
				active_projects = user.active_projects()
				if len(active_projects) == 1:
					new_reservation.project = active_projects[0]
				else:
					try:
						new_reservation.project = Project.objects.get(id=request.POST['project_id'])
					except:
						return render(request, 'calendar/project_choice.html', {'active_projects': active_projects})

			else:
				# add ReservationProject entries for the customers submitted by the staff member
				# a check before saving
				try:
					policy_problems = None
					overridable = None
					policy_problems, overridable = check_policy_to_save_reservation(request, None, new_reservation, user, explicit_policy_override)
					if policy_problems is not None and policy_problems != []:
						return render(request, 'calendar/policy_dialog.html', {'policy_problems': policy_problems, 'overridable': overridable and request.user.is_staff})
				except Exception as ex:
					logger.exception(str(ex))
					return HttpResponseBadRequest('A problem occurred while checking for conflicting reservations')

				new_reservation.save()

				if not ReservationProject.objects.filter(reservation=new_reservation).exists():
					reservation_projects = {}
					sample_selections = {}	
					for key, value in request.POST.items():
						if is_valid_field(key):
							attribute, separator, index = key.partition("__")
							index = int(index)
							if index not in reservation_projects:
								reservation_projects[index] = ReservationProject()
								reservation_projects[index].reservation = new_reservation
								reservation_projects[index].created = timezone.now()
								reservation_projects[index].updated = timezone.now()
							if attribute == "chosen_user":
								if value is not None and value != "":
									reservation_projects[index].customer = User.objects.get(id=value)
								else:
									new_reservation.delete()
									return HttpResponseBadRequest('Please choose a user for whom the tool will be run.')
							if attribute == "chosen_project":
								if value is not None and value != "" and value != "-1":
									reservation_projects[index].project = Project.objects.get(id=value)
								else:
									new_reservation.delete()
									return HttpResponseBadRequest('Please choose a project for charges made during this run.')

							if attribute == "chosen_sample":
								sample_field = "selected_sample__" + str(index)
								samples = request.POST.get(sample_field)
								sample_selections[index] = samples.split(",")


					for r in reservation_projects.values():
						r.full_clean()
						r.save()
					

	configured = (request.POST.get('configured') == "true")
	# If a reservation is requested and the tool does not require configuration...
	if not tool.is_configurable():
		new_reservation.updated = timezone.now()
		# a check before saving
		try:
			policy_problems = None
			overridable = None
			policy_problems, overridable = check_policy_to_save_reservation(request, None, new_reservation, user, explicit_policy_override)
			if policy_problems is not None and policy_problems != []:
				return render(request, 'calendar/policy_dialog.html', {'policy_problems': policy_problems, 'overridable': overridable and request.user.is_staff})
		except Exception as ex:
			logger.exception(str(ex))
			return HttpResponseBadRequest('An error occurred while attempting to verify the timing of your reservation')

		new_reservation.save()

		if new_reservation.project is not None and new_reservation.user is not None:
			if not ReservationProject.objects.filter(reservation=new_reservation).exists():
				res_proj = ReservationProject()
				res_proj.reservation = new_reservation
				res_proj.customer = new_reservation.user
				res_proj.project = new_reservation.project
				res_proj.created = timezone.now()
				res_proj.updated = timezone.now()
				res_proj.save()

		# save any samples
		# check for a group of samples
		if reservation_projects is not None and reservation_projects != {}:
			if sample_selections is not None:
				for k in reservation_projects.keys():
					if k in sample_selections:
						for s in sample_selections[k]:
							reservation_projects[k].sample.add(Sample.objects.get(id=int(s)))

			else:
				samples = request.POST['selected_sample']
				sample_list = samples.split(",")

				if sample_list != [] and sample_list != "" and sample_list != ['']:
					rp = ReservationProject.objects.filter(reservation=new_reservation)
					for r in rp:
						for s in sample_list:
							r.sample.add(Sample.objects.get(id=int(s)))
		else:
			samples = request.POST['selected_sample']
			sample_list = samples.split(",")

			if sample_list != [] and sample_list != "" and sample_list != ['']:
				rp = ReservationProject.objects.filter(reservation=new_reservation)
				for r in rp:
					for s in sample_list:
						r.sample.add(Sample.objects.get(id=int(s)))

		# create an email with the reservation information
		if b_send_mail:

			subject = str(tool.name) + ' reservation created'

			if ReservationProject.objects.filter(reservation=new_reservation).exists():
				rp = ReservationProject.objects.filter(reservation=new_reservation)
				if rp[0].customer != request.user:
					subject += ' for ' + str(rp[0].customer)
					if rp.count() > 1:
						subject += ' and others'
			msg = 'You have created a reservation for the ' + str(tool.name) + ' starting ' + str(new_reservation.start) + '.'

			# attempted fix for timezone offset error in calendar invite
			res_info = Reservation.objects.get(id=int(new_reservation.id))

			attachment = create_ics_for_reservation(request, res_info, False)
			#send_mail(subject='Reservation Created', content=msg, from_email='LEOHelp@psu.edu', to=[str(new_reservation.user.email)], attachments=[attachment])
			email = EmailMessage('Reservation Created',msg,'LEOHelp@psu.edu',[str(new_reservation.user.email)],reply_to=['LEOHelp@psu.edu'])
			email.attach(attachment)
			create_email_log(email, EmailCategory.GENERAL)
			email.send()


		return HttpResponse()

	# If a reservation is requested and the tool requires configuration that has not been submitted...
	elif tool.is_configurable() and not configured:
		configuration_information = tool.get_configuration_information(user=user, start=start)
		try:
			configuration_information['reservation_id'] = new_reservation.id
		except:
			configuration_information['reservation_id'] = None
		return render(request, 'calendar/configuration.html', configuration_information)

	# If a reservation is requested and configuration information is present also...
	elif tool.is_configurable() and configured:
		new_reservation.additional_information, new_reservation.self_configuration, res_conf = extract_configuration(request)
		# Reservation can't be short notice if the user is configuring the tool themselves.
		if new_reservation.self_configuration:
			new_reservation.short_notice = False
		new_reservation.updated = timezone.now()

		# a check before saving
		try:
			policy_problems = None
			overridable = None
			policy_problems, overridable = check_policy_to_save_reservation(request, None, new_reservation, user, explicit_policy_override)
			if policy_problems is not None and policy_problems != []:
				return render(request, 'calendar/policy_dialog.html', {'policy_problems': policy_problems, 'overridable': overridable and request.user.is_staff})
		except Exception as ex:
			logger.exception(str(ex))
			return HttpResponseBadRequest('An error occurred while attempting to verify the timing of your reservation')

		new_reservation.save()
		for rc in res_conf:
			if rc is not None:
				rc.reservation = new_reservation
				rc.updated = timezone.now()
				rc.save()

		if new_reservation.project is not None and new_reservation.user is not None:
			if not ReservationProject.objects.filter(reservation=new_reservation).exists():
				res_proj = ReservationProject()
				res_proj.reservation = new_reservation
				res_proj.customer = new_reservation.user
				res_proj.project = new_reservation.project
				res_proj.created = timezone.now()
				res_proj.updated = timezone.now()
				res_proj.save()

		# check for any samples to save
		if request.POST.get('staff_charge') == "customer":
			# check for customer info 
			# reservation_projects and sample_selections will be empty even if called previously since this path of code results from the submission of configuration information, on this passthrough the code to generate these variables will be skipped
			reservation_projects = {}
			sample_selections = {}

			for key, value in request.POST.items():
				if is_valid_field(key):
					attribute, separator, index = key.partition("__")
					index = int(index)

					if index not in reservation_projects:
						if attribute == "chosen_project":
							res_proj = ReservationProject.objects.filter(project=Project.objects.get(id=int(value)), reservation=new_reservation)
							reservation_projects[index] = res_proj[0]

					if attribute == "chosen_sample":
						sample_field = "selected_sample__" + str(index)
						samples = request.POST.get(sample_field)
						sample_selections[index] = samples.split(",")

		# after repopulating the variables we can do our checks as if we were on the path of a non-configurable tool
		if reservation_projects is not None and reservation_projects != {}:
			if sample_selections is not None and sample_selections != {}:
				for k in reservation_projects.keys():
					if k in sample_selections:
						for s in sample_selections[k]:
							reservation_projects[k].sample.add(Sample.objects.get(id=int(s)))

		else:
			samples = request.POST['selected_sample']
			sample_list = samples.split(",")

			if sample_list != [] and sample_list != "" and sample_list != ['']:
				rp = ReservationProject.objects.filter(reservation=new_reservation)
				for r in rp:
					for s in sample_list:
						smp = Sample.objects.get(id=int(s))
						if smp in r.project.sample_project.all():
							r.sample.add(smp)


		if b_send_mail:
			subject = str(tool.name) + ' reservation created'

			if ReservationProject.objects.filter(reservation=new_reservation).exists():
				rp = ReservationProject.objects.filter(reservation=new_reservation)
				if rp[0].customer != request.user:
					subject += ' for ' + str(rp[0].customer)
					if rp.count() > 1:
						subject += ' and others'
				
			msg = 'You have created a reservation for the ' + str(tool.name) + ' starting ' + str(new_reservation.start) + '.'

			# attempted fix for timezone offset error
			res_info = Reservation.objects.get(id=int(new_reservation.id))
			attachment = create_ics_for_reservation(request, res_info, False)
			email = EmailMessage(subject,msg,'LEOHelp@psu.edu',[str(new_reservation.user.email)],reply_to=['LEOHelp@psu.edu'])
			email.attach(attachment)
			create_email_log(email, EmailCategory.GENERAL)
			email.send()


		return HttpResponse()

	return HttpResponseBadRequest("Reservation creation failed because invalid parameters were sent to the server.")


def extract_configuration(request):
	cleaned_configuration = []
	conf = []
	for key, value in request.POST.items():
		entry = parse_configuration_entry(key, value)
		if entry is not None:
			cleaned_configuration.append(entry)
	# Sort by configuration display priority and join the results:
	result = ''
	for config in sorted(cleaned_configuration):
		conf.append(config[2])
		result += config[1] + '\n'
	if 'additional_information' in request.POST:
		result += request.POST['additional_information'][:ADDITIONAL_INFORMATION_MAXIMUM_LENGTH].strip()
	self_configuration = True if request.POST.get('self_configuration') == 'on' else False
	return result, self_configuration, conf


def parse_configuration_entry(key, value):
	if value == "" or not match("^configuration_[0-9]+__slot_[0-9]+__display_priority_[0-9]+$", key):
		return None
	config_id, slot, display_priority = [int(s) for s in key.split('_') if s.isdigit()]
	configuration = Configuration.objects.get(pk=config_id)
	available_setting = configuration.get_available_setting(value)
	res_conf = ReservationConfiguration()
	if configuration.available_settings is None or configuration.available_settings == '':
		res_conf.configuration = configuration
		consumable_id = int(value)
		res_conf.consumable = Consumable.objects.get(id=consumable_id)
	else:
		res_conf.configuration = configuration
		setting = str(configuration.get_available_setting(value))
		res_conf.setting = setting
	if res_conf.configuration is None:
		res_conf = None
	if len(configuration.current_settings_as_list()) == 1:
		return display_priority, configuration.name + " needs to be set to " + available_setting + ".", res_conf
	else:
		return display_priority, configuration.configurable_item_name + " #" + str(slot + 1) + " needs to be set to " + available_setting + ".", res_conf


@staff_member_required(login_url=None)
@require_POST
def create_outage(request):
	""" Create a reservation for a user. """
	try:
		start, end = extract_times(request.POST)
	except Exception as e:
		return HttpResponseBadRequest(str(e))
	tool = get_object_or_404(Tool, name=request.POST.get('tool_name'))
	# Create the new reservation:
	outage = ScheduledOutage()
	outage.created = timezone.now()
	outage.creator = request.user
	outage.category = request.POST.get('category', '')[:200]
	outage.tool = tool
	outage.start = start
	outage.end = end

	# If there was a problem in saving the reservation then return the error...
	policy_problem = check_policy_to_create_outage(outage, request)
	if policy_problem:
		return HttpResponseBadRequest(policy_problem)

	# Make sure there is at least an outage title
	if not request.POST.get('title'):
		dictionary = {'categories': ScheduledOutageCategory.objects.all()}
		return render(request, 'calendar/scheduled_outage_information.html', dictionary)

	outage.title = request.POST['title']
	outage.details = request.POST.get('details', '')

	outage.updated = timezone.now()
	outage.save()
	return HttpResponse()


@login_required
@require_POST
def resize_reservation(request):
	""" Resize a reservation for a user. """
	try:
		delta = timedelta(minutes=int(request.POST['delta']))
	except:
		return HttpResponseBadRequest('Invalid delta')
	return modify_reservation(request, None, delta)


@staff_member_required(login_url=None)
@require_POST
def resize_outage(request):
	""" Resize an outage """
	try:
		delta = timedelta(minutes=int(request.POST['delta']))
	except:
		return HttpResponseBadRequest('Invalid delta')
	return modify_outage(request, None, delta)


@login_required
@require_POST
def move_reservation(request):
	""" Move a reservation for a user. """
	try:
		delta = timedelta(minutes=int(request.POST['delta']))
	except:
		return HttpResponseBadRequest('Invalid delta')
	return modify_reservation(request, delta, delta)


@staff_member_required(login_url=None)
@require_POST
def move_outage(request):
	""" Move a reservation for a user. """
	try:
		delta = timedelta(minutes=int(request.POST['delta']))
	except:
		return HttpResponseBadRequest('Invalid delta')
	return modify_outage(request, delta, delta)


def modify_reservation(request, start_delta, end_delta):
	"""
	Cancel the user's old reservation and create a new one. Reservations are cancelled and recreated so that
	reservation abuse can be tracked if necessary. This function should be called by other views and should
	not be tied directly to a URL.
	"""
	try:
		reservation_to_cancel = Reservation.objects.get(pk=request.POST['id'])
	except Reservation.DoesNotExist:
		return HttpResponseNotFound("The reservation that you wish to modify doesn't exist!")

	b_send_mail = False
	mail_setting = UserProfileSetting.objects.get(name="RESERVATION_CALENDAR_INVITES")

	if UserProfile.objects.filter(user=request.user, setting=mail_setting).exists():
		setting = UserProfile.objects.get(user=request.user, setting=mail_setting)
		b_send_mail = bool(int(setting.value))

	response = check_policy_to_cancel_reservation(reservation_to_cancel, request.user, request)
	# Do not move the reservation if the user was not authorized to cancel it.
	if response.status_code != HTTPStatus.OK:
		return response
	# Record the current time so that the timestamp of the cancelled reservation and the new reservation match exactly.
	now = timezone.now()
	# set the tool
	tool = reservation_to_cancel.tool
	# Cancel the user's original reservation.
	reservation_to_cancel.cancelled = True
	reservation_to_cancel.cancellation_time = now
	reservation_to_cancel.cancelled_by = request.user
	# Create a new reservation for the user.
	new_reservation = Reservation()
	new_reservation.created = now
	new_reservation.title = reservation_to_cancel.title
	new_reservation.creator = request.user
	new_reservation.additional_information = reservation_to_cancel.additional_information
	# A change in start time will only be provided if the reservation is being moved.
	new_reservation.start = reservation_to_cancel.start
	new_reservation.self_configuration = reservation_to_cancel.self_configuration
	new_reservation.short_notice = False
	if start_delta:
		new_reservation.start += start_delta
	if new_reservation.self_configuration:
		# Reservation can't be short notice since the user is configuring the tool themselves.
		new_reservation.short_notice = False
	else:
		new_reservation.short_notice = determine_insufficient_notice(reservation_to_cancel.tool, new_reservation.start)
	# A change in end time will always be provided for reservation move and resize operations.
	new_reservation.end = reservation_to_cancel.end + end_delta
	new_reservation.tool = reservation_to_cancel.tool
	new_reservation.project = reservation_to_cancel.project
	new_reservation.user = reservation_to_cancel.user
	new_reservation.creation_time = now
	policy_problems, overridable = check_policy_to_save_reservation(request, reservation_to_cancel, new_reservation, request.user, False)
	if policy_problems:
		return HttpResponseBadRequest(policy_problems[0])
	else:
		# All policy checks passed, so save the reservation.
		new_reservation.updated = timezone.now()
		new_reservation.save()
		if ReservationConfiguration.objects.filter(reservation=reservation_to_cancel).exists:
			for rc in ReservationConfiguration.objects.filter(reservation=reservation_to_cancel):
				res_conf = ReservationConfiguration()
				res_conf.created = timezone.now()
				res_conf.reservation = new_reservation
				res_conf.configuration = rc.configuration
				res_conf.consumable = rc.consumable
				res_conf.setting = rc.setting
				res_conf.updated = timezone.now()
				res_conf.save()

		if ReservationProject.objects.filter(reservation=reservation_to_cancel).exists():
			for rp in ReservationProject.objects.filter(reservation=reservation_to_cancel):
				res_proj = ReservationProject()
				res_proj.reservation = new_reservation
				res_proj.project = rp.project
				res_proj.customer = rp.customer
				res_proj.created = timezone.now()
				res_proj.updated = timezone.now()
				res_proj.save()

				# update sample relationships
				for s in rp.sample.all():
					res_proj.sample.add(s)

		reservation_to_cancel.descendant = new_reservation
		reservation_to_cancel.updated = timezone.now()
		reservation_to_cancel.save()

	if b_send_mail:
		msg = 'You have cancelled a reservation for the ' + str(tool.name) + ' starting ' + str(reservation_to_cancel.start) + '.'
		attachment = create_ics_for_reservation(request, reservation_to_cancel, True)
		email = EmailMessage('Reservation Cancelled',msg,'LEOHelp@psu.edu',[str(reservation_to_cancel.user.email)],reply_to=['LEOHelp@psu.edu'])
		email.attach(attachment)
		create_email_log(email, EmailCategory.GENERAL)
		email.send()

	#if ReservationProject.objects.filter(reservation=reservation_to_cancel).exists():
	#	for rp in ReservationProject.objects.filter(reservation=reservation_to_cancel):
	#		msg = 'A reservation has been cancelled for the ' + str(tool.name) + ' starting ' + str(reservation_to_cancel.start) + '.'
	#		email = EmailMessage('Reservation Cancelled',msg,'LEOHelp@psu.edu',[str(rp.customer.email)],reply_to=['LEOHelp@psu.edu'])
	#		email.attach(attachment)
	#		create_email_log(email, EmailCategory.GENERAL)
	#		email.send()

	if b_send_mail:
		msg = 'You have created a reservation for the ' + str(tool.name) + ' starting ' + str(new_reservation.start) + '.'

		# attempted fix for timezone offset error
		res_info = Reservation.objects.get(id=int(new_reservation.id))
		attachment = create_ics_for_reservation(request, res_info, False)
		email = EmailMessage('Reservation Created',msg,'LEOHelp@psu.edu',[str(new_reservation.user.email)],reply_to=['LEOHelp@psu.edu'])
		email.attach(attachment)
		create_email_log(email, EmailCategory.GENERAL)
		email.send()

	#if ReservationProject.objects.filter(reservation=new_reservation).exists():
	#	for rp in ReservationProject.objects.filter(reservation=new_reservation):
	#		msg = 'A reservation has been created for the ' + str(tool.name) + ' starting ' + str(new_reservation.start) + '.  The tool will be run by ' + str(new_reservation.user)
	#		email = EmailMessage('Reservation Created',msg,'LEOHelp@psu.edu',[str(rp.customer.email)],reply_to=['LEOHelp@psu.edu'])
	#		email.attach(attachment)
	#		create_email_log(email, EmailCategory.GENERAL)
	#		email.send()

	return response


def modify_outage(request, start_delta, end_delta):
	try:
		outage = ScheduledOutage.objects.get(pk=request.POST['id'])
	except ScheduledOutage.DoesNotExist:
		return HttpResponseNotFound("The outage that you wish to modify doesn't exist!")
	if start_delta:
		outage.start += start_delta
	outage.end += end_delta
	policy_problem = check_policy_to_create_outage(outage, request)
	if policy_problem:
		return HttpResponseBadRequest(policy_problem)
	else:
		# All policy checks passed, so save the reservation.
		outage.updated = timezone.now()
		outage.save()
	return HttpResponse()


def determine_insufficient_notice(tool, start):
	""" Determines if a reservation is created that does not give the
	Laboratory staff sufficient advance notice to configure a tool. """
	for config in tool.configuration_set.all():
		advance_notice = start.replace(tzinfo=None) - timezone.now().replace(tzinfo=None)
		if advance_notice < timedelta(hours=config.advance_notice_limit):
			return True
	return False


@login_required
@require_POST
def cancel_reservation(request, reservation_id):
	""" Cancel a reservation for a user. """
	reservation = get_object_or_404(Reservation, id=reservation_id)
	response = check_policy_to_cancel_reservation(reservation, request.user, request)
	# Staff must provide a reason when cancelling a reservation they do not own.
	reason = parse_parameter_string(request.POST, 'reason')
	if reservation.user != request.user and not reason:
		response = HttpResponseBadRequest("You must provide a reason when cancelling someone else's reservation.")

	if response.status_code == HTTPStatus.OK:
		# All policy checks passed, so cancel the reservation.
		reservation.cancelled = True
		reservation.cancellation_time = timezone.now()
		reservation.cancelled_by = request.user
		reservation.updated = timezone.now()
		reservation.save()

		# check for notification requests and fulfill
		notify = ReservationNotification.objects.filter(reservation=reservation)

		for n in notify:
			details = {
				'user': n.user,
				'reservation': reservation,
			}

			email_contents = get_media_file_contents('notification_request.html')
			if email_contents:
				notification_email = Template(email_contents).render(Context(details))
				n.user.email_user(str(dateformat.format(reservation.start, "m-d-Y g:i:s A")) + ' time slot for the ' + str(reservation.tool.name) + ' just opened', notification_email, n.user.email)
			


		if reason:
			dictionary = {
				'staff_member': request.user,
				'reservation': reservation,
				'reason': reason,
				'template_color': bootstrap_primary_color('info')
			}
			email_contents = get_media_file_contents('cancellation_email.html')
			if email_contents:
				cancellation_email = Template(email_contents).render(Context(dictionary))
				reservation.user.email_user('Your reservation was cancelled', cancellation_email, request.user.email)

	b_send_mail = False
	mail_setting = UserProfileSetting.objects.get(name="RESERVATION_CALENDAR_INVITES")

	if UserProfile.objects.filter(user=request.user, setting=mail_setting).exists():
		setting = UserProfile.objects.get(user=request.user, setting=mail_setting)
		b_send_mail = bool(int(setting.value))

	if b_send_mail:
		msg = 'You have cancelled a reservation for the ' + str(reservation.tool.name) + ' starting ' + str(reservation.start) + '.'
		attachment = create_ics_for_reservation(request, reservation, True)
		email = EmailMessage('Reservation Cancelled',msg,'LEOHelp@psu.edu',[str(reservation.user.email)],reply_to=['LEOHelp@psu.edu'])
		email.attach(attachment)
		create_email_log(email, EmailCategory.GENERAL)
		email.send()

	#if ReservationProject.objects.filter(reservation=reservation).exists():
	#	for rp in ReservationProject.objects.filter(reservation=reservation):
	#		msg = 'A reservation has been cancelled for the ' + str(reservation.tool.name) + ' starting ' + str(reservation.start) + '.'
	#		email = EmailMessage('Reservation Cancelled',msg,'LEOHelp@psu.edu',[str(rp.customer.email)],reply_to=['LEOHelp@psu.edu'])
	#		email.attach(attachment)
	#		create_email_log(email, EmailCategory.GENERAL)
	#		email.send()

	if request.device == 'desktop':
		return response
	if request.device == 'mobile':
		if response.status_code == HTTPStatus.OK:
			return render(request, 'mobile/cancellation_result.html', {'event_type': 'Reservation', 'tool': reservation.tool})
		else:
			return render(request, 'mobile/error.html', {'message': response.content})


@staff_member_required(login_url=None)
@require_POST
def cancel_outage(request, outage_id):
	outage = get_object_or_404(ScheduledOutage, id=outage_id)
	outage.delete()
	if request.device == 'desktop':
		return HttpResponse()
	if request.device == 'mobile':
		dictionary = {'event_type': 'Scheduled outage', 'tool': outage.tool}
		return render(request, 'mobile/cancellation_result.html', dictionary)


@login_required
@require_POST
def set_reservation_title(request, reservation_id):
	try:
		reservation = get_object_or_404(Reservation, id=reservation_id)
		reservation.title = request.POST.get('title', '')[:reservation._meta.get_field('title').max_length]
		reservation.updated = timezone.now()
		reservation.save()
	except Exception as inst:
		return HttpResponseBadRequest(inst)

	return HttpResponse()


@login_required
@permission_required('NEMO.trigger_timed_services', raise_exception=True)
@require_GET
def email_reservation_reminders(request):
	return do_email_reservation_reminders()


def do_email_reservation_reminders():
	# Exit early if the reservation reminder email template has not been customized for the organization yet.
	reservation_reminder_message = get_media_file_contents('reservation_reminder_email.html')
	reservation_warning_message = get_media_file_contents('reservation_warning_email.html')
	if not reservation_reminder_message or not reservation_warning_message:
		return HttpResponseNotFound('The reservation reminder email template has not been customized for your organization yet. Please visit the NEMO customizable_key_values page to upload a template, then reservation reminder email notifications can be sent.')

	# Find all reservations that are two hours from now, plus or minus 5 minutes to allow for time skew.
	preparation_time = 120
	tolerance = 5
	earliest_start = timezone.now() + timedelta(minutes=preparation_time) - timedelta(minutes=tolerance)
	latest_start = timezone.now() + timedelta(minutes=preparation_time) + timedelta(minutes=tolerance)
	upcoming_reservations = Reservation.objects.filter(cancelled=False, start__gt=earliest_start, start__lt=latest_start)
	# Email a reminder to each user with an upcoming reservation.
	for reservation in upcoming_reservations:
		tool = reservation.tool
		if tool.operational and not tool.problematic() and tool.all_resources_available():
			subject = reservation.tool.name + " reservation reminder"
			rendered_message = Template(reservation_reminder_message).render(Context({'reservation': reservation, 'template_color': bootstrap_primary_color('success')}))
		elif not tool.operational or tool.required_resource_is_unavailable():
			subject = reservation.tool.name + " reservation problem"
			rendered_message = Template(reservation_warning_message).render(Context({'reservation': reservation, 'template_color': bootstrap_primary_color('danger'), 'fatal_error': True}))
		else:
			subject = reservation.tool.name + " reservation warning"
			rendered_message = Template(reservation_warning_message).render(Context({'reservation': reservation, 'template_color': bootstrap_primary_color('warning'), 'fatal_error': False}))
		user_office_email = get_customization('user_office_email_address')

		b_send_mail = False
		mail_setting = UserProfileSetting.objects.get(name="RESERVATION_REMINDER")
		if UserProfile.objects.filter(user=reservation.user, setting=mail_setting).exists():
			setting = UserProfile.objects.get(user=reservation.user, setting=mail_setting)
			b_send_mail = bool(int(setting.value))
		if b_send_mail:
			reservation.user.email_user(subject, rendered_message, user_office_email)

	return HttpResponse()


@login_required
@permission_required('NEMO.trigger_timed_services', raise_exception=True)
@require_GET
def email_usage_reminders(request):
	projects_to_exclude = request.GET.getlist("projects_to_exclude[]")
	busy_users = AreaAccessRecord.objects.filter(end=None, staff_charge=None, active_flag=True).exclude(project__id__in=projects_to_exclude)
	busy_tools = UsageEvent.objects.filter(end=None, active_flag=True).exclude(project__id__in=projects_to_exclude)

	# Make lists of all the things a user is logged in to.
	# We don't want to send 3 separate emails if a user is logged into three things.
	# Just send one email for all the things!
	aggregate = {}
	for access_record in busy_users:
		key = str(access_record.customer)
		aggregate[key] = {
			'email': access_record.customer.email,
			'first_name': access_record.customer.first_name,
			'resources_in_use': [str(access_record.area)],
		}
	for usage_event in busy_tools:
		key = str(usage_event.operator)
		if key in aggregate:
			aggregate[key]['resources_in_use'].append(usage_event.tool.name)
		else:
			aggregate[key] = {
				'email': usage_event.operator.email,
				'first_name': usage_event.operator.first_name,
				'resources_in_use': [usage_event.tool.name],
			}

	user_office_email = get_customization('user_office_email_address')

	message = get_media_file_contents('usage_reminder_email.html')
	if message:
		subject = "Laboratory usage"
		for user in aggregate.values():
			rendered_message = Template(message).render(Context({'user': user}))
			send_mail(subject, '', user_office_email, [user['email']], html_message=rendered_message)

	message = get_media_file_contents('staff_charge_reminder_email.html')
	if message:
		busy_staff = StaffCharge.objects.filter(end=None, active_flag=True)
		for staff_charge in busy_staff:
			subject = "Active staff charge since " + format_datetime(staff_charge.start)
			rendered_message = Template(message).render(Context({'staff_charge': staff_charge}))
			staff_charge.staff_member.email_user(subject, rendered_message, user_office_email)

	return HttpResponse()


@login_required
@require_GET
def reservation_details(request, reservation_id):
	reservation = get_object_or_404(Reservation, id=reservation_id)
	if reservation.cancelled:
		error_message = 'This reservation was cancelled by {0} at {1}.'.format(reservation.cancelled_by, format_datetime(reservation.cancellation_time))
		return HttpResponseNotFound(error_message)
	if ReservationProject.objects.filter(reservation=reservation).exists():
		rp =  ReservationProject.objects.filter(reservation=reservation)
	else:
		rp = None
	return render(request, 'calendar/reservation_details.html', {'reservation': reservation, 'rp': rp})


@login_required
@require_GET
def outage_details(request, outage_id):
	outage = get_object_or_404(ScheduledOutage, id=outage_id)
	return render(request, 'calendar/outage_details.html', {'outage': outage})

#                  Oringal usage_details
# @login_required
# @require_GET
# def usage_details(request, event_id):
# 	event = get_object_or_404(UsageEvent, id=event_id)
# 	return render(request, 'calendar/usage_details.html', {'event': event})


@login_required
@require_GET
def usage_details(request, event_id):
    event = get_object_or_404(UsageEvent, id=event_id)
    uep = UsageEventProject.objects.filter(usage_event=event).select_related('project', 'customer')
    
    # Customer string 
    customers =({str(r.customer) for r in uep if r.customer})
     # Project string 
    projects = (f"{r.project.project_number} - {r.project.name}" for r in uep if r.project)
   
    
	# Annotate the event 
    event.customer_string = ", ".join(customers) if customers else "No customers"
    event.project_string = " | ".join(projects) if projects else "No projects"

    return render(request, 'calendar/usage_details.html', {'event': event})


@login_required
@require_GET
def area_access_details(request, event_id):
	event = get_object_or_404(AreaAccessRecord, id=event_id)
	return render(request, 'calendar/area_access_details.html', {'event': event})


@login_required
@require_GET
@permission_required('NEMO.trigger_timed_services', raise_exception=True)
def cancel_unused_reservations(request):
	return do_cancel_unused_reservations()


def do_cancel_unused_reservations():
	# Exit early if the missed reservation email template has not been customized for the organization yet.
	if not get_media_file_contents('missed_reservation_email.html'):
		return HttpResponseNotFound('The missed reservation email template has not been customized for your organization yet. Please visit the NEMO customizable_key_values page to upload a template, then missed email notifications can be sent.')

	tools = Tool.objects.filter(visible=True, operational=True, missed_reservation_threshold__isnull=False)
	missed_reservations = []
	for tool in tools:
		# If a tool is in use then there's no need to look for unused reservation time.
		if tool.in_use() or tool.required_resource_is_unavailable() or tool.scheduled_outage_in_progress():
			continue
		# Calculate the timestamp of how long a user can be late for a reservation.
		threshold = (timezone.now() - timedelta(minutes=tool.missed_reservation_threshold))
		threshold = datetime.replace(threshold, second=0, microsecond=0)  # Round down to the nearest minute.
		# Find the reservations that began exactly at the threshold.
		reservation = Reservation.objects.filter(cancelled=False, missed=False, shortened=False, tool=tool, user__is_staff=False, start=threshold, end__gt=timezone.now())
		for r in reservation:
			# Staff may abandon reservations.
			if r.user.is_staff:
				continue
			# If there was no tool enable or disable event since the threshold timestamp then we assume the reservation has been missed.
			if not (UsageEvent.objects.filter(tool=tool, start__gte=threshold, active_flag=True).exists() or UsageEvent.objects.filter(tool=tool, end__gte=threshold, active_flag=True).exists()):
				# Mark the reservation as missed and notify the user & laboratory staff.
				r.missed = True
				r.updated = timezone.now()
				r.save()
				missed_reservations.append(r)

			else:
				# is the UsageEvent related to the current user?
				if (UsageEvent.objects.filter(tool=tool, start__gte=threshold, active_flag=True).exists() or UsageEvent.objects.filter(tool=tool, end__gte=threshold, active_flag=True).exists()):
					usage_events = UsageEvent.objects.filter(Q(tool=tool), Q(operator=r.user), Q(active_flag=True), Q(start__gte=threshold) | Q(end__gte=threshold))
					if usage_events.count() > 0:
						continue
					else:
						r.missed = True
						r.updated = timezone.now()
						r.save()
						missed_reservations.append(r)


	for r in missed_reservations:
		send_missed_reservation_notification(r)

	return HttpResponse()


@staff_member_required(login_url=None)
@require_GET
def proxy_reservation(request):
	if request.user.is_superuser:
		users = User.objects.filter(is_active=True, projects__active=True).distinct()
	elif request.user.groups.filter(name="Administrative Staff").exists() or request.user.groups.filter(name="Core Admin").exists():
		users = User.objects.filter(is_active=True, projects__active=True).distinct()
	elif request.user.groups.filter(name="Technical Staff").exists():
		users = User.objects.filter(is_active=True, projects__active=True).distinct()
	else:
		users = User.objects.filter(id=request.user.id)

	return render(request, 'calendar/proxy_reservation.html', {'users': users })


def send_missed_reservation_notification(reservation):
	subject = "Missed reservation for the " + str(reservation.tool)
	message = get_media_file_contents('missed_reservation_email.html')
	message = Template(message).render(Context({'reservation': reservation}))
	user_office_email = get_customization('user_office_email_address')
	abuse_email = get_customization('abuse_email_address')
	send_mail(subject, '', user_office_email, [reservation.user.email, abuse_email, user_office_email], html_message=message)

	# check for notification requests and fulfill
	notify = ReservationNotification.objects.filter(reservation=reservation)

	for n in notify:
		details = {
			'user': n.user,
			'reservation': reservation,
		}

		email_contents = get_media_file_contents('notification_request.html')
		if email_contents:
			notification_email = Template(email_contents).render(Context(details))
			n.user.email_user(str(dateformat.format(reservation.start, "m-d-Y g:i:s A")) + ' time slot for the ' + str(reservation.tool.name) + ' just opened', notification_email, n.user.email)

def is_valid_field(field):
	return search("^(chosen_user|chosen_project|project_percent|chosen_sample)__[0-9]+$", field) is not None


@login_required
@require_POST
def create_notification(request):
	res = get_object_or_404(Reservation, id=request.POST.get("reservation_id"))
	user = get_object_or_404(User, id=request.POST.get("user_id"))

	notify = ReservationNotification()
	notify.reservation = res
	notify.user = user
	notify.save()

	return HttpResponse()


@login_required
@require_POST
def delete_notification(request):
	res = get_object_or_404(Reservation, id=request.POST.get("reservation_id"))
	user = get_object_or_404(User, id=request.POST.get("user_id"))

	notify = ReservationNotification.objects.get(user=user, reservation=res)
	notify.delete()

	return HttpResponse()


@login_required
@require_POST
def save_notifications(request):
	tool_ids = request.POST.get("tool_ids")
	tool_list = tool_ids.split(",")
	reservations = Reservation.objects.filter(tool__id__in=tool_list, start__gt=request.POST.get("start"), start__lt=request.POST.get("end"))

	for r in reservations:
		rn = ReservationNotification()
		rn.reservation = Reservation.objects.get(id=r.id)
		rn.user = User.objects.get(id=request.user.id)
		rn.save()

	return HttpResponse()


@login_required
@require_POST
def create_reservation_customer_calendar_invite(request, reservation_id):
	reservation = Reservation.objects.get(id=reservation_id)
	tool = reservation.tool
	if ReservationProject.objects.filter(reservation=reservation).exists():
		reservation_projects = ReservationProject.objects.filter(reservation=reservation)
		for rp in reservation_projects:
			subject = str(tool.name) + ' reservation (' + str(rp.project) + ')'
			msg = 'A reservation for the ' + str(tool.name) + ' has been scheduled to perform work on the project ' + str(rp.project)
			attachment = create_ics_for_reservation(request, reservation, False)
			email = EmailMessage(subject,msg,'LEOHelp@psu.edu',[str(rp.customer.email)],reply_to=['LEOHelp@psu.edu'])
			email.attach(attachment)
			create_email_log(email, EmailCategory.GENERAL)
			email.send()

	return HttpResponse()

@login_required
@require_POST
def create_reservation_calendar_invite(request, reservation_id):
	reservation = Reservation.objects.get(id=reservation_id)
	tool = reservation.tool
	subject = str(tool.name) + ' reservation created'
	if ReservationProject.objects.filter(reservation=reservation).exists():
		rp = ReservationProject.objects.filter(reservation=reservation)
		if rp[0].customer != request.user:
			subject += ' for ' + str(rp[0].customer)
			if rp.count() > 1:
				subject += ' and others'
	msg = 'You have a reservation scheduled for the ' + str(tool.name) + ' starting at ' + str(reservation.start) + '.'
	attachment = create_ics_for_reservation(request, reservation, False)
	email = EmailMessage(subject,msg,'LEOHelp@psu.edu',[str(reservation.user.email)],reply_to=['LEOHelp@psu.edu'])
	email.attach(attachment)
	create_email_log(email, EmailCategory.GENERAL)
	email.send()

	return HttpResponse()

def create_ics_for_reservation(request, reservation, cancelled=False):
	site_title = 'LEO'
	reservation_organizer_email = getattr(settings, "RESERVATION_ORGANIZER_EMAIL", "LEOHelp@psu.edu")
	reservation_organizer = getattr(settings, "RESERVATION_ORGANIZER", site_title)
	method_name = 'CANCEL' if cancelled else 'REQUEST'
	method = f'METHOD:{method_name}\n'
	status = 'STATUS:CANCELLED\n' if cancelled else 'STATUS:CONFIRMED\n'
	uid = 'UID:'+str(reservation.id)+'\n'
	sequence = 'SEQUENCE:2\n' if cancelled else 'SEQUENCE:0\n'
	priority = 'PRIORITY:5\n' if cancelled else 'PRIORITY:0\n'
	now = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
	start = reservation.start.strftime('%Y%m%dT%H%M%SZ')
	end = reservation.end.strftime('%Y%m%dT%H%M%SZ')
	#now = timezone.now()
	#start = reservation.start
	#end = reservation.end

	if reservation.title is not None and reservation.title != '':
		reservation_name = reservation.title
	else:
		reservation_name = str(reservation.tool.name)

		if ReservationProject.objects.filter(reservation=reservation).exists():
			rp = ReservationProject.objects.filter(reservation=reservation)
			if rp[0].customer != request.user:
				reservation_name += ' for ' + str(rp[0].customer) + ' [' + str(rp[0].project.project_number) + ']'
				if rp.count() > 1:
					reservation_name += ' and others'

	lines = ['BEGIN:VCALENDAR\n', 'VERSION:2.0\n', method, 'BEGIN:VEVENT\n', uid, sequence, priority, f'DTSTAMP:{now}\n', f'DTSTART:{start}\n', f'DTEND:{end}\n', f'ATTENDEE;CN="{reservation.user.get_full_name()}";RSVP=TRUE:mailto:{reservation.user.email}\n', f'ORGANIZER;CN="{reservation_organizer}":mailto:{reservation_organizer_email}\n', f'SUMMARY:[{site_title}] {reservation_name}\n', status, 'END:VEVENT\n', 'END:VCALENDAR\n']
	ics = io.StringIO('')
	ics.writelines(lines)
	ics.seek(0)

	attachment = create_email_attachment(ics, maintype='text', subtype='calendar', method=method_name)
	return attachment


@login_required
def multi_calendar_view(request):

	def format_slot(slot):
		return {
			"start": slot[0].strftime("%m/%d/%Y %I:%M %p"),
			"end": slot[1].strftime("%m/%d/%Y %I:%M %p"),
		}

	events = []
	error_messages = []
	slot_duration = None
	window_start = None
	window_end = None

	if request.method == "POST":
		form = MultiCalendarForm(request.POST)
		if form.is_valid():

			slot_duration = form.cleaned_data['slot_duration']
			window_start = form.cleaned_data['window_start']
			window_end = form.cleaned_data['window_end']

			# Parse manual ICS URLs as "Short Name:URL"
			manual_url_map = {}
			for line in form.cleaned_data['ics_urls'].splitlines():
				line = line.strip()
				if not line:
					continue
				if ':' in line:
					short_name, url = line.split(':', 1)
					manual_url_map[url.strip()] = short_name.strip()
				else:
					manual_url_map[line] = line  # fallback: use URL as name

			# User-selected calendar links
			selected_users = form.cleaned_data.get('users_with_calendars')
			user_url_map = {}
			if selected_users:
				for u in selected_users:
					if u.user_shareable_calendar_link:
						user_url_map[u.user_shareable_calendar_link] = u.get_full_name()

			# Combine all URLs and their sources
			all_url_map = {**user_url_map, **manual_url_map}

			for url, source_name in all_url_map.items():
				try:
					response = requests.get(url, timeout=10)
					response.raise_for_status()
					cal = Calendar.from_ical(response.text)
					for component in cal.walk():
						if component.name == "VEVENT":
							event = Event.from_ical(component.to_ical())
							dtstart = event.get('dtstart')
							dtend = event.get('dtend')
							summary = event.get('summary')
							location = event.get('location')
							rrule = event.get('rrule')
							exdate = event.get('exdate')

							if not dtstart or not summary:
								continue

							start_dt = dtstart.dt if hasattr(dtstart, 'dt') else dtstart
							end_dt = dtend.dt if dtend and hasattr(dtend, 'dt') else None

							# Recurrence handling
							if rrule:
								# Build exclusion set
								exdates = set()
								if exdate:
									if isinstance(exdate, vDDDLists):
										ex_items = exdate.dts
									elif isinstance(exdate, list):
										ex_items = exdate
									else:
										ex_items = [exdate]
									for ex_item in ex_items:
										actual_ex_dt = ex_item.dt if hasattr(ex_item, 'dt') else ex_item
										if isinstance(actual_ex_dt, (datetime.date, datetime.datetime)):
											exdates.add(actual_ex_dt.date())

								# Prepare rrule start
								rrule_dtstart = start_dt
								if isinstance(rrule_dtstart, datetime.date) and not isinstance(rrule_dtstart, datetime.datetime):
									rrule_dtstart = datetime.datetime(rrule_dtstart.year, rrule_dtstart.month, rrule_dtstart.day, 0, 0, 0)
								if rrule_dtstart.tzinfo is None:
									rrule_dtstart = rrule_dtstart.replace(tzinfo=UTC)

								# Expand recurrences for the next N days (e.g., 30 days)
								rule_set = rrulestr(rrule.to_ical().decode('utf-8'), dtstart=rrule_dtstart)
								occurrences = rule_set.between(window_start, window_end, inc=True)

								for occ_start in occurrences:
									occ_date = occ_start.date()
									if occ_date not in exdates:
										occ_end = occ_start + (end_dt - start_dt if end_dt else datetime.timedelta(hours=1))
										events.append({
											"source": source_name,
											"title": str(summary),
											"start": ensure_datetime(occ_start),
											"end": ensure_datetime(occ_end),
											"location": str(location) if location else "",
											"type": "external"
										})
							else:
							# Non-recurring event
								events.append({
									"source": source_name,
									"title": str(summary),
									"start": ensure_datetime(start_dt),
									"end": ensure_datetime(end_dt),
									"location": str(location) if location else "",
									"type": "external"
								})
				except Exception as e:
					error_messages.append(f"Failed to load {url}: {e}")

			# Handle LEO tool reservations
			tools = form.cleaned_data['tools_selected']
			if tools:
				reservations = Reservation.objects.filter(
					tool__in=tools, cancelled=False, missed=False, shortened=False
				)
				for r in reservations:
					events.append({
						"source": "LEO",
						"title": f"{r.tool.name} reservation",
						"start": ensure_datetime(r.start),
						"end": ensure_datetime(r.end),
						"location": "",
						"type": "leo"
					})
	else:
		form = MultiCalendarForm()

	now = datetime.datetime.now(UTC)
	events = [e for e in events if e["start"] and e["start"] >= now]

	# Sort events by start time
	events.sort(key=lambda e: e["start"] if e["start"] else datetime.datetime.max)

	# Group events by source
	events_by_source = defaultdict(list)
	for e in events:
		events_by_source[e["source"]].append(e)

	# Convert to a list of lists for find_available_slots
	events_grouped = list(events_by_source.values())

	available_slots = []
	if (
		slot_duration is not None
		and window_start is not None
		and window_end is not None
		and events_grouped  # Only call if there are sources
	):
		available_slots = find_available_slots(events_grouped, slot_duration, window_start, window_end)

	if available_slots:
		available_slots = [format_slot(slot) for slot in available_slots]

	return render(request, "calendar/multi_calendar.html", {
		"form": form,
		"events": events,
		"available_slots": available_slots,
		"errors": error_messages,
	})

def ensure_datetime(dt):
	if isinstance(dt, datetime.datetime):
		if dt.tzinfo is None:
			# Make naive datetimes UTC-aware
			return dt.replace(tzinfo=UTC)
		return dt
	elif isinstance(dt, datetime.date):
		# Convert date to UTC-aware datetime at midnight
		return datetime.datetime(dt.year, dt.month, dt.day, tzinfo=UTC)
	return dt

def find_available_slots(list_of_events, duration_minutes, window_start, window_end, max_results=3):
	# list_of_events: list of lists of {"start": datetime, "end": datetime}
	# duration_minutes: int
	# window_start, window_end: datetime
	# Returns: list of (start, end) tuples

	def get_free_intervals(busy, window_start, window_end):
		busy = sorted([(e["start"], e["end"]) for e in busy if e["start"] and e["end"]])
		merged = []
		for s, e in busy:
			if not merged or s > merged[-1][1]:
				merged.append([s, e])
			else:
				merged[-1][1] = max(merged[-1][1], e)
		free = []
		prev_end = window_start
		for s, e in merged:
			if s > prev_end:
				free.append((prev_end, s))
			prev_end = max(prev_end, e)
		if prev_end < window_end:
			free.append((prev_end, window_end))
		return free

	def intersect_intervals(lists):
		if not lists:
			return []
		result = lists[0]
		for free in lists[1:]:
			new_result = []
			i, j = 0, 0
			while i < len(result) and j < len(free):
				a_start, a_end = result[i]
				b_start, b_end = free[j]
				start = max(a_start, b_start)
				end = min(a_end, b_end)
				if start < end:
					new_result.append((start, end))
				if a_end < b_end:
					i += 1
				else:
					j += 1
			result = new_result
			if not result:
				break
		return result

	def is_business_hours(dt_start, dt_end):
		# Monday=0, Sunday=6
		if dt_start.weekday() > 4 or dt_end.weekday() > 4:
			return False
		business_start = dt_start.replace(hour=8, minute=0, second=0, microsecond=0)
		business_end = dt_start.replace(hour=17, minute=0, second=0, microsecond=0)
		return (dt_start >= business_start and dt_end <= business_end)

	# 1. Get free intervals for each source
	free_intervals_per_source = [
		get_free_intervals(events, window_start, window_end)
		for events in list_of_events
	]

	# 2. Intersect all free intervals
	common_free = intersect_intervals(free_intervals_per_source)

	# 3. Find slots of required duration within business hours
	slots = []
	delta = datetime.timedelta(minutes=duration_minutes)
	step = datetime.timedelta(minutes=15)
	for s, e in common_free:
		slot_start = s
		while slot_start + delta <= e:
			slot_end = slot_start + delta
			if is_business_hours(slot_start, slot_end):
				slots.append((slot_start, slot_end))
				if len(slots) >= max_results:
					return slots
			slot_start += step
	return slots


def find_next_available_slot(tool, duration_minutes, after_time):
	# Find the next available slot for the tool after 'after_time'
	# This is a simplified version; you may want to use your existing logic for business hours, etc.
	busy = Reservation.objects.filter(
		tool=tool,
		cancelled=False,
		missed=False,
		shortened=False,
		end__gt=after_time
	).order_by('start')

	slot_start = after_time
	slot_end = slot_start + datetime.timedelta(minutes=duration_minutes)
	for res in busy:
		if slot_end <= res.start:
			return slot_start, slot_end
		slot_start = max(slot_start, res.end)
		slot_end = slot_start + datetime.timedelta(minutes=duration_minutes)
	return slot_start, slot_end

def sequential_tool_schedule(request):
	if request.method == "POST":
		formset = ToolDurationFormSet(request.POST)
		if formset.is_valid():
			schedule = []
			current_time = timezone.now()
			for form in formset:
				tool = form.cleaned_data['tool']
				duration = form.cleaned_data['duration']
				start, end = find_next_available_slot(tool, duration, current_time)
				schedule.append({
					'tool': tool,
					'start': start,
					'end': end,
				})
				current_time = end
			return render(request, "calendar/sequential_tool_schedule.html", {
				"formset": formset,
				"schedule": schedule,
			})
	else:
		formset = ToolDurationFormSet()
	return render(request, "calendar/sequential_tool_schedule.html", {
		"formset": formset,
	})