from datetime import datetime, timedelta
from itertools import chain
from re import match, search

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_time, parse_date, parse_datetime
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST
from django.utils.html import escape
from django.utils.safestring import mark_safe

from NEMO.models import Reservation, ReservationProject, Sample, Tool, User, Project, ScheduledOutage
from NEMO.utilities import extract_date, localize, beginning_of_the_day, end_of_the_day
from NEMO.views.calendar import extract_configuration, determine_insufficient_notice
from NEMO.views.policy import check_policy_to_save_reservation


@login_required
@require_GET
def choose_tool(request, next_page):
	dictionary = {
		'tools': Tool.objects.filter(visible=True).order_by('category', 'name'),
	}

	ctools = Tool.objects.filter(visible=True).order_by('category', 'name')

	categorized_tools = "["
	for t in ctools:
		categorized_tools += '{{"name":"{0}", "id":{1}}},'.format(escape(str(t.category))+"/"+escape(str(t.name)), t.id)
	categorized_tools = categorized_tools.rstrip(",") + "]"
	categorized_tools = mark_safe(categorized_tools)

	dictionary['cat_tools'] = categorized_tools

	if next_page == 'view_calendar':
		# If the user has no active projects then they're not allowed to make reservations. Redirect them home.
		if request.user.active_project_count() == 0:
			return render(request, 'mobile/no_active_projects.html')
		dictionary['title'] = "Which tool calendar would you like to view?"
		dictionary['next_page'] = 'view_calendar'
	elif next_page == 'tool_control':
		dictionary['title'] = "Which tool control page would you like to view?"
		dictionary['next_page'] = 'tool_control'
	return render(request, 'mobile/choose_tool.html', dictionary)


@login_required
@require_GET
def new_reservation(request, tool_id, date=None):
	# If the user has no active projects then they're not allowed to make reservations.
	if request.user.active_project_count() == 0:
		return render(request, 'mobile/no_active_projects.html')

	tool = get_object_or_404(Tool, id=tool_id)
	start_value = ''
	end_value = ''

	#if date:
	#	date = parse_datetime(str(date))
	#	date = date.astimezone(timezone.get_current_timezone())

	dictionary = tool.get_configuration_information(user=request.user, start=None)
	dictionary['tool'] = tool
	dictionary['date'] = date
	dictionary['users'] = User.objects.filter(is_active=True, projects__active=True).exclude(id=request.user.id).distinct()
	#dictionary['start_value'] = start_value
	#dictionary['end_value'] = end_value
	#dictionary['start_date'] = str(datetime.today().year) + '-' + str(datetime.today().month) + '-' + str(datetime.today().day) 

	return render(request, 'mobile/new_reservation.html', dictionary)


@login_required
@require_POST
@csrf_exempt
def make_reservation(request):
	try:
		#date = parse_date(request.POST['date'])
		#start = localize(datetime.combine(date, parse_time(request.POST['start'])))
		#end = localize(datetime.combine(date, parse_time(request.POST['end'])))
		start = request.POST['start']
		end = request.POST['end']

		if start is None or start == '' or end is None or end == '':
			raise Exception()
	except:
		return render(request, 'mobile/error.html', {'message': 'Please enter a valid start time and end time for the reservation.'})

	mode = ""
	start_value = parse_datetime(str(start))
	#start_value = start_value.astimezone(timezone.get_current_timezone())
	end_value = parse_datetime(str(end))
	#end_value = end_value.astimezone(timezone.get_current_timezone())
	tool = get_object_or_404(Tool, id=request.POST.get('tool_id'))
	# Create the new reservation:
	reservation = Reservation()
	reservation.user = request.user
	reservation.creator = request.user
	reservation.tool = tool
	reservation.start = start_value.astimezone(timezone.get_current_timezone())
	reservation.end = end_value.astimezone(timezone.get_current_timezone())
	reservation.short_notice = determine_insufficient_notice(tool, start_value)
	policy_problems, overridable = check_policy_to_save_reservation(request, None, reservation, request.user, False)

	# If there was a problem in saving the reservation then return the error...
	if policy_problems:
		return render(request, 'mobile/error.html', {'message': policy_problems[0]})

	# All policy checks have passed.

	if request.user.is_staff:
		mode = request.POST['staff_charge']

		if mode == "self":
			# make a reservation for the user and don't add a record to the ReservationProject table
			active_projects = request.user.active_projects()

			if len(active_projects) == 1:
				reservation.project = active_projects[0]
			else:
				try:
					reservation.project = Project.objects.get(id=request.POST['project_id'])
				except:
					msg = 'No project was selected.  Please return to the <a href="/calendar/">calendar</a> to try again.'
					return render(request, 'mobile/error.html', {'message': msg})

		else:
			# add ReservationProject entries for the customers submitted by the staff member
			reservation_projects = {}
			reservation.save()
			sample_selections = {}

			for key, value in request.POST.items():
				if is_valid_field(key):
					attribute, separator, index = key.partition("__")
					index = int(index)
					if index not in reservation_projects:
						reservation_projects[index] = ReservationProject()
						reservation_projects[index].reservation = reservation
						reservation_projects[index].created = timezone.now()
						reservation_projects[index].updated = timezone.now()
					if attribute == "chosen_user":
						if value is not None and value != "":
							reservation_projects[index].customer = User.objects.get(id=value)
						else:
							reservation.delete()
							return HttpResponseBadRequest('Please choose a user for whom the tool will be run.')
					if attribute == "chosen_project":
						if value is not None and value != "" and value != "-1":
							reservation_projects[index].project = Project.objects.get(id=value)
						else:
							reservation.delete()
							return HttpResponseBadRequest('Please choose a project for charges made during this run.')

					if attribute == "chosen_sample":
						sample_field = "selected_sample__" + str(index)
						samples = request.POST.get(sample_field)
						sample_selections[index] = samples.split(",")


			for r in reservation_projects.values():
				r.full_clean()
				r.save()

			for k in reservation_projects.keys():
				if k in sample_selections:
					for s in sample_selections[k]:
						reservation_projects[k].sample.add(Sample.objects.get(id=int(s)))

	else:
		try:
			reservation.project = Project.objects.get(id=request.POST['project_id'])
		except:
			if not request.user.is_staff:
				return render(request, 'mobile/error.html', {'message': 'You must specify a project for your reservation'})

	reservation.additional_information, reservation.self_configuration, res_conf = extract_configuration(request)
	# Reservation can't be short notice if the user is configuring the tool themselves.
	if reservation.self_configuration:
		reservation.short_notice = False
	policy_problems, overridable = check_policy_to_save_reservation(request, None, reservation, request.user, False)

	reservation.created = timezone.now()
	reservation.updated = timezone.now()
	reservation.save()

	for rc in res_conf:
		rc.reservation = reservation
		rc.save()

	if not ReservationProject.objects.filter(reservation=reservation).exists():
		res_proj = ReservationProject()
		res_proj.reservation = reservation
		res_proj.customer = reservation.user
		res_proj.project = reservation.project
		res_proj.created = timezone.now()
		res_proj.updated = timezone.now()
		res_proj.save()

	if (not request.user.is_staff) or (request.user.is_staff and mode == "self"):
		samples = request.POST['selected_sample']
		sample_list = samples.split(",")

		if sample_list != [] and sample_list != ['']:
			rp = ReservationProject.objects.filter(reservation=reservation)
			for r in rp:
				for s in sample_list:
					smp = Sample.objects.get(id=int(s))
					if smp in r.project.sample_project.all():
						r.sample.add(smp)

	return render(request, 'mobile/reservation_success.html', {'new_reservation': reservation})


@login_required
@require_GET
def view_calendar(request, tool_id, date=None):
	tool = get_object_or_404(Tool, id=tool_id)
	if date:
		try:
			date = extract_date(date)
		except:
			render(request, 'mobile/error.html', {'message': 'Invalid date requested for tool calendar'})
			return HttpResponseBadRequest()
	else:
		date = datetime.now()

	start = beginning_of_the_day(date, in_local_timezone=True)
	end = end_of_the_day(date, in_local_timezone=True)

	reservations = Reservation.objects.filter(tool=tool, cancelled=False, missed=False, shortened=False)
	# Exclude events for which the following is true:
	# The event starts and ends before the time-window, and...
	# The event starts and ends after the time-window.
	reservations = reservations.exclude(start__lt=start, end__lt=start)
	reservations = reservations.exclude(start__gt=end, end__gt=end)

	outages = ScheduledOutage.objects.filter(Q(tool=tool) | Q(resource__fully_dependent_tools__in=[tool]))
	outages = outages.exclude(start__lt=start, end__lt=start)
	outages = outages.exclude(start__gt=end, end__gt=end)

	events = list(chain(reservations, outages))
	events.sort(key=lambda x: x.start)

	dictionary = {
		'tool': tool,
		'previous_day': start - timedelta(days=1),
		'current_day': start,
		'current_day_string': date.strftime('%Y-%m-%d'),
		'next_day': start + timedelta(days=1),
		'events': events,
		'user': request.user,
	}

	return render(request, 'mobile/view_calendar.html', dictionary)

def is_valid_field(field):
	return search("^(chosen_user|chosen_project|project_percent|chosen_sample)__[0-9]+$", field) is not None
