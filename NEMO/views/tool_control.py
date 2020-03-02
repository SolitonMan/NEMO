from re import search

import requests

from copy import deepcopy
from datetime import timedelta
from http import HTTPStatus
from itertools import chain

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseNotFound, HttpResponseServerError, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import logger, require_GET, require_POST, require_http_methods
from django.utils.dateparse import parse_time, parse_date, parse_datetime
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.urls import reverse

from NEMO.forms import CommentForm, nice_errors, ToolForm
from NEMO.models import AreaAccessRecord, AreaAccessRecordProject, Comment, Configuration, ConfigurationHistory, Project, Reservation, ReservationConfiguration, StaffCharge, StaffChargeProject, Task, TaskCategory, TaskStatus, Tool, UsageEvent, UsageEventProject, User
from NEMO.utilities import extract_times, quiet_int
from NEMO.views.policy import check_policy_to_disable_tool, check_policy_to_enable_tool, check_policy_to_enable_tool_for_multi
from NEMO.widgets.dynamic_form import DynamicForm
from NEMO.widgets.tool_tree import ToolTree


@staff_member_required(login_url=None)
@require_GET
def tools(request):
	if request.user.is_superuser:
		tool_list = Tool.objects.all().order_by('name')
	else:
		tool_list = Tool.objects.filter(core_id__in=request.user.core_ids.all()).order_by('name')
	return render(request, 'tool_control/tools.html', { 'tools': tool_list })


@staff_member_required(login_url=None)
@require_http_methods(['GET', 'POST'])
def create_or_modify_tool(request, tool_id):
	dictionary = {
		'tool_id': tool_id,
	}

	try:
		tool = Tool.objects.get(id=tool_id)
	except:
		tool = None

	if request.method == 'GET':
		dictionary['form'] = ToolForm(instance=tool)
		return render(request, 'tool_control/create_or_modify_tool.html', dictionary)

	elif request.method == 'POST':
		form = ToolForm(request.POST, instance=tool)
		dictionary['form'] = form

		if not form.is_valid():
			return render(request, 'tool_control/create_or_modify_tool.html', dictionary)

		form.save()
		return redirect('tools')


@login_required
@require_GET
def tool_control(request, tool_id=None, qualified_only=None, core_only=None):

	""" Presents the tool control view to the user, allowing them to being/end using a tool or see who else is using it. """
	if request.user.active_project_count() == 0:
		return render(request, 'no_project.html')

	# The tool-choice sidebar is not available for mobile devices, so redirect the user to choose a tool to view.
	if request.device == 'mobile' and tool_id is None:
		return redirect('choose_tool', next_page='tool_control')

	tools = Tool.objects.filter(visible=True).order_by('category', 'name')
	ctools = Tool.objects.filter(visible=True).order_by('category', 'name')

	if qualified_only == '1':
		tools = tools.filter(id__in=request.user.qualifications.all()).order_by('category', 'name')
		ctools = ctools.filter(id__in=request.user.qualifications.all()).order_by('category', 'name')

	if core_only == '1':
		tools = tools.filter(Q(core_id__in=request.user.core_ids.all()) | Q(id__in=request.user.qualifications.all())).order_by('category', 'name')
		ctools = ctools.filter(Q(core_id__in=request.user.core_ids.all()) | Q(id__in=request.user.qualifications.all())).order_by('category', 'name')

	# create searchable names for tools that include the category
	categorized_tools = "["
	for t in ctools:
		categorized_tools += '{{"name":"{0}", "id":{1}}},'.format(escape(str(t.category))+"/"+escape(str(t.name)), t.id)
	categorized_tools = categorized_tools.rstrip(",") + "]"
	categorized_tools = mark_safe(categorized_tools)

	users = User.objects.filter(is_active=True, projects__active=True, projects__account__active=True).exclude(id=request.user.id).distinct()

	dictionary = {
		'tools': tools,
		'selected_tool': tool_id,
		'qualified_only': qualified_only,
		'core_only': core_only,
		'cat_tools': categorized_tools,
		'users': users,
	}


	if request.user.charging_staff_time():
		# retrieve staff charges to provide a current listing of customers
		staff_charge = request.user.get_staff_charge()
		staff_charge_projects = StaffChargeProject.objects.filter(staff_charge=staff_charge.id)

		scp_out = "["

		for s in staff_charge_projects:
			scp_out += '{{"project":"{0}", "customer":"{1}", "project_id":"{2}", "user_id":"{3}"}},'.format(escape(str(s.project)), escape(str(s.customer)), escape(str(s.project.id)), escape(str(s.customer.id)))
		scp_out = scp_out.rstrip(",") + "]"
		scp_out = mark_safe(scp_out)

		dictionary['staff_charge_projects'] = scp_out


	# The tool-choice sidebar only needs to be rendered for desktop devices, not mobile devices.
	if request.device == 'desktop':
		dictionary['rendered_tool_tree_html'] = ToolTree().render(None, {'tools': tools})

	return render(request, 'tool_control/tool_control.html', dictionary)


@login_required
@require_GET
def tool_status(request, tool_id):
	""" Gets the current status of the tool (that is, whether it is currently in use or not). """
	tool = get_object_or_404(Tool, id=tool_id, visible=True)

	dictionary = {
		'tool': tool,
		'task_categories': TaskCategory.objects.filter(stage=TaskCategory.Stage.INITIAL_ASSESSMENT),
		'mobile': request.device == 'mobile',
		'task_statuses': TaskStatus.objects.all(),
		'post_usage_questions': DynamicForm(tool.post_usage_questions).render(),
	}

	try:
		#current_reservation = Reservation.objects.get(start__lt=timezone.now(), end__gt=timezone.now(), cancelled=False, missed=False, shortened=False, user=request.user, tool=tool)
		current_reservation = request.user.current_reservation_for_tool(tool)
		if current_reservation is not None:
			dictionary['time_left'] = current_reservation.end
			dictionary['my_reservation'] = current_reservation
			# set configuration to reservation
			#for rc in current_reservation.reservationconfiguration_set.all():
			#	if rc.configuration.available_settings is None or rc.configuration.available_settings == '':
			#		rc.configuration.replace_current_setting(0, rc.consumable.id)
			#	else:
			#		setting_id = rc.configuration.get_setting_id(rc.setting)
			#		if setting_id is not None:
			#			rc.configuration.replace_current_setting(0, setting_id)
			#tool.update_post_usage_questions()
	except Reservation.DoesNotExist:
		pass

	dictionary['rendered_configuration_html'] = tool.configuration_widget(request.user)
	tool.update_post_usage_questions()

	# Staff need the user list to be able to qualify users for the tool.
	if request.user.is_staff:
		dictionary['users'] = User.objects.filter(is_active=True, projects__active=True, projects__account__active=True).distinct()

	return render(request, 'tool_control/tool_status.html', dictionary)


@staff_member_required(login_url=None)
@require_GET
def use_tool_for_other(request, entry_number):
	dictionary = {
		'users': User.objects.filter(is_active=True, projects__active=True, projects__account__active=True).exclude(id=request.user.id).distinct(),
		'entry_number': entry_number
	}
	return render(request, 'tool_control/use_tool_for_other.html', dictionary)


@login_required
@require_POST
def tool_configuration(request):
	""" Sets the current configuration of a tool. """
	try:
		configuration = Configuration.objects.get(id=request.POST['configuration_id'])
	except:
		return HttpResponseNotFound('Configuration not found.')
	if configuration.tool.in_use():
		return HttpResponseBadRequest('Cannot change a configuration while a tool is in use.')
	if not configuration.user_is_maintainer(request.user):
		return HttpResponseBadRequest('You are not authorized to change this configuration.')
	try:
		slot = int(request.POST['slot'])
		choice = int(request.POST['choice'])
	except:
		return HttpResponseBadRequest('Invalid configuration parameters.')
	try:
		configuration.replace_current_setting(slot, choice)
	except IndexError:
		return HttpResponseBadRequest('Invalid configuration choice.')
	configuration.save()
	history = ConfigurationHistory()
	history.configuration = configuration
	history.slot = slot
	history.user = request.user
	history.setting = configuration.get_current_setting(slot)
	history.save()
	configuration.tool.update_post_usage_questions()
	return HttpResponse()


@login_required
@require_POST
def create_comment(request):
	form = CommentForm(request.POST)
	if not form.is_valid():
		return HttpResponseBadRequest(nice_errors(form).as_ul())
	comment = form.save(commit=False)
	comment.content = comment.content.strip()
	comment.author = request.user
	comment.expiration_date = None if form.cleaned_data['expiration'] == 0 else timezone.now() + timedelta(days=form.cleaned_data['expiration'])
	comment.save()
	return redirect('tool_control')


@login_required
@require_POST
def hide_comment(request, comment_id):
	comment = get_object_or_404(Comment, id=comment_id)
	if comment.author_id != request.user.id and not request.user.is_staff:
		return HttpResponseBadRequest("You may only hide a comment if you are its author or a staff member.")
	comment.visible = False
	comment.hidden_by = request.user
	comment.hide_date = timezone.now()
	comment.save()
	return redirect('tool_control')


def determine_tool_status(tool):
	# Make the tool operational when all problems are resolved that require a shutdown.
	if tool.task_set.filter(force_shutdown=True, cancelled=False, resolved=False).count() == 0:
		tool.operational = True
	else:
		tool.operational = False
	tool.save()


@login_required
@require_POST
def enable_tool(request, tool_id, user_id, project_id, staff_charge):
	""" Enable a tool for a user. The user must be qualified to do so based on the lab usage policy. """

	if not settings.ALLOW_CONDITIONAL_URLS:
		return HttpResponseBadRequest('Tool control is only available on campus. We\'re working to change that! Thanks for your patience.')

	tool = get_object_or_404(Tool, id=tool_id)
	operator = request.user
	user = get_object_or_404(User, id=user_id)
	project = get_object_or_404(Project, id=project_id)
	staff_charge = staff_charge == 'true'
	response = check_policy_to_enable_tool(tool, operator, user, project, staff_charge, request)
	if response.status_code != HTTPStatus.OK:
		return response

	# All policy checks passed so enable the tool for the user.
	if tool.interlock and not tool.interlock.unlock():
		raise Exception("The interlock command for this tool failed. The error message returned: " + str(tool.interlock.most_recent_reply))


	# check for reservation and configuration and configure for tool appropriately
	"""
	try:
		current_reservation = Reservation.objects.get(start__lte=timezone.now(), end__gt=timezone.now(), user=request.user, tool=tool, cancelled=False, missed=False)

		# update project
		project = current_reservation.project

		# adjust configuration if any
		res_conf = ReservationConfiguration.objects.filter(reservation=current_reservation)

		for rc in res_conf:
			config = Configuration.objects.get(id=rc.configuration.id)
			if rc.setting is None or rc.setting == '':
				config.current_settings = str(rc.consumable.id)
			else:
				config.current_settings = str(rc.setting)
			config.save()
		tool.update_post_usage_questions()
	except Reservation.DoesNotExist:
		pass
	"""


	# Create a new usage event to track how long the user uses the tool.
	new_usage_event = UsageEvent()
	new_usage_event.operator = operator
	new_usage_event.user = user
	new_usage_event.project = project
	new_usage_event.tool = tool
	new_usage_event.created = timezone.now()
	new_usage_event.updated = timezone.now()
	new_usage_event.save()

	# create a usage event project record for consistency with other usage event charges
	uep = UsageEventProject()
	uep.usage_event = new_usage_event
	uep.customer = user
	uep.project = project
	uep.project_percent = 100.0	# no reason to ask after the fact when only one customer
	uep.created = timezone.now()
	uep.updated = timezone.now()
	uep.save()

	if staff_charge:
		new_staff_charge = StaffCharge()
		new_staff_charge.staff_member = request.user
		new_staff_charge.customer = user
		new_staff_charge.project = project
		new_staff_charge.created = timezone.now()
		new_staff_charge.updated = timezone.now()
		new_staff_charge.save()

		# create a staff_charge_project record
		scp = StaffChargeProject()
		scp.staff_charge = new_staff_charge
		scp.customer = user
		scp.project = project
		scp.created = timezone.now()
		scp.updated = timezone.now()
		scp.save()

	if tool.requires_area_access and AreaAccessRecord.objects.filter(area=tool.requires_area_access,customer=operator,end=None).count() == 0:
		aar = AreaAccessRecord()
		aar.area = tool.requires_area_access
		aar.customer = operator
		aar.project = project
		aar.start = timezone.now()
		aar.created = timezone.now()
		aar.updated = timezone.now()

		if staff_charge:
			aar.staff_charge = new_staff_charge

		aar.save()

		# create area access record project
		aarp = AreaAccessRecordProject()
		aarp.area_access_record = aar
		aarp.project = project
		aarp.customer = user
		aarp.created = timezone.now()
		aarp.updated = timezone.now()
		aarp.save()

	return response

@staff_member_required(login_url=None)
@require_POST
def enable_tool_multi(request):
	""" Enable a tool for a single operator to charge to multiple customers.  """
	id = 0
	try:
		id = int(request.POST.get('tool_id'))
	except ValueError:
			return HttpResponseBadRequest('request.POST.get(\'tool_id\') = ' + request.POST.get('tool_id'))
	tool = get_object_or_404(Tool, id=id)
	operator = request.user

	# check for an existing reservation
	try:
		current_reservation = Reservation.objects.get(start__lte=timezone.now(), end__gt=timezone.now(), cancelled=False, missed=False, user=operator, tool=tool)
		res_conf = ReservationConfiguration.objects.filter(reservation=current_reservation)
		for rc in res_conf:
			config = Configuration.objects.get(id=rc.configuration.id)
			if rc.setting is None or rc.setting == '':
				config.current_settings = str(rc.consumable.id)
			else:
				config.current_settings = str(rc.setting)
			config.save()
		tool.update_post_usage_questions()
	except Reservation.DoesNotExist:
		pass
	# initiate a UsageEvent
	new_usage_event = UsageEvent()
	new_usage_event.operator = operator
	new_usage_event.tool = tool
	new_usage_event.project = None
	new_usage_event.user = None
	new_usage_event.created = timezone.now()
	new_usage_event.updated = timezone.now()
	new_usage_event.save()	

	project_events = {}

	for key, value in request.POST.items():
		if is_valid_field(key):
			attribute, separator, index = key.partition("__")
			index = int(index)
			if index not in project_events:
				project_events[index] = UsageEventProject()
				project_events[index].usage_event = new_usage_event
				project_events[index].created = timezone.now()
				project_events[index].updated = timezone.now()
			if attribute == "chosen_user":
				if value is not None and value != "":
					project_events[index].customer = User.objects.get(id=value)
				else:
					new_usage_event.delete()
					return HttpResponseBadRequest('Please choose a user for whom the tool will be run.')
			if attribute == "chosen_project":
				if value is not None and value != "" and value != "-1":
					project_events[index].project = Project.objects.get(id=value)
				else:
					new_usage_event.delete()
					return HttpResponseBadRequest('Please choose a project for charges made during this run.')

			if hasattr(project_events[index], 'customer') and hasattr(project_events[index], 'project'):
				response = check_policy_to_enable_tool_for_multi(tool, operator, project_events[index].customer, project_events[index].project, request)
				if response.status_code != HTTPStatus.OK:
					return response

	for p in project_events.values():
		p.full_clean(exclude='project_percent')
		p.save()

	# All policy checks passed so enable the tool for the user.
	if tool.interlock and not tool.interlock.unlock():
		raise Exception("The interlock command for this tool failed. The error message returned: " + str(tool.interlock.most_recent_reply))

	# record staff charges
	if request.user.charging_staff_time():
		if request.POST.get("override_staff_charge") == "true":
			current_staff_charge = request.user.get_staff_charge()
			current_staff_charge.charge_end_override = True
			current_staff_charge.override_confirmed = False
			current_staff_charge.end = timezone.now()
			current_staff_charge.updated = timezone.now()
			current_staff_charge.save()
			new_staff_charge = StaffCharge()
			new_staff_charge.staff_member = request.user
			new_staff_charge.created = timezone.now()
			new_staff_charge.updated = timezone.now()
			new_staff_charge.save()
		else:
			new_staff_charge = request.user.get_staff_charge()
	else:
		new_staff_charge = StaffCharge()
		new_staff_charge.staff_member = request.user
		new_staff_charge.created = timezone.now()
		new_staff_charge.updated = timezone.now()
		new_staff_charge.save()

	project_charges = {}

	for key, value in request.POST.items():
		if is_valid_field(key):
			attribute, separator, index = key.partition("__")
			index = int(index)
			if index not in project_charges:
				project_charges[index] = StaffChargeProject()
				project_charges[index].staff_charge = new_staff_charge
				project_charges[index].created = timezone.now()
				project_charges[index].updated = timezone.now()
			if attribute == "chosen_user":
				if value is not None and value != "":
					project_charges[index].customer = User.objects.get(id=value)
				else:
					new_staff_charge.delete()
					new_usage_event.delete()
					return HttpResponseBadRequest('Please choose a user for whom the tool will be run.')
			if attribute == "chosen_project":
				if value is not None and value != "" and value != "-1":
					project_charges[index].project = Project.objects.get(id=value)
				else:
					new_staff_charge.delete()
					new_usage_event.delete()
					return HttpResponseBadRequest('Please choose a project for charges made during this run.')

	for p in project_charges.values():
		if not StaffChargeProject.objects.filter(staff_charge=p.staff_charge, customer=p.customer, project=p.project).exists():
			p.full_clean(exclude='project_percent')
			p.save()
		 
	if tool.requires_area_access and AreaAccessRecord.objects.filter(area=tool.requires_area_access,customer=operator,end=None).count() == 0:
		aar = AreaAccessRecord()
		aar.area = tool.requires_area_access
		aar.start = timezone.now()
		aar.created = timezone.now()
		aar.updated = timezone.now()

		if staff_charge:
			aar.staff_charge = new_staff_charge

		aar.save()

		if staff_charge:
			scp = StaffChargeProject.objects.filter(staff_charge=new_staff_charge)

			for s in scp:
				aarp = AreaAccessRecordProject()
				aarp.area_access_record = aar
				aarp.project = s.project
				aarp.customer = s.customer
				aarp.created = timezone.now()
				aarp.updated = timezone.now()
				aarp.save()

	return response


def is_valid_field(field):
	return search("^(chosen_user|chosen_project|project_percent)__[0-9]+$", field) is not None


@staff_member_required(login_url=None)
@require_GET
def usage_event_entry(request):
	entry_number = int(request.GET['entry_number'])
	return render(request, 'tool_control/usage_event_entry.html', {'entry_number': entry_number})


@login_required
def disable_tool(request, tool_id):

	if not settings.ALLOW_CONDITIONAL_URLS:
		return HttpResponseBadRequest('Tool control is only available on campus.')

	tool = get_object_or_404(Tool, id=tool_id)
	if tool.get_current_usage_event() is None:
		return HttpResponse()
	downtime = timedelta(minutes=quiet_int(request.POST.get('downtime')))
	response = check_policy_to_disable_tool(tool, request.user, downtime, request)
	if response.status_code != HTTPStatus.OK:
		return response
	try:
		current_reservation = Reservation.objects.get(start__lt=timezone.now(), end__gt=timezone.now(), cancelled=False, missed=False, shortened=False, user=request.user, tool=tool)
		# Staff are exempt from mandatory reservation shortening when tool usage is complete.
		if request.user.is_staff is False:
			# Shorten the user's reservation to the current time because they're done using the tool.
			new_reservation = deepcopy(current_reservation)
			new_reservation.id = None
			new_reservation.pk = None
			new_reservation.end = timezone.now() + downtime
			new_reservation.updated = timezone.now()
			new_reservation.created = timezone.now()
			new_reservation.save()
			current_reservation.shortened = True
			current_reservation.updated = timezone.now()
			current_reservation.descendant = new_reservation
			current_reservation.save()
	except Reservation.DoesNotExist:
		pass

	# All policy checks passed so disable the tool for the user.
	if tool.interlock and not tool.interlock.lock():
		error_message = f"The interlock command for the {tool} failed. The error message returned: {tool.interlock.most_recent_reply}"
		logger.error(error_message)
		return HttpResponseServerError(error_message)

	# End the current usage event for the tool
	current_usage_event = tool.get_current_usage_event()
	current_usage_event.end = timezone.now() + downtime

	# Collect post-usage questions
	dynamic_form = DynamicForm(tool.post_usage_questions)
	current_usage_event.run_data = dynamic_form.extract(request)


	if current_usage_event.project is None and current_usage_event.user is None:
		# multi user event possibility, check
		current_usage_event.updated = timezone.now()
		current_usage_event.save()
		if UsageEventProject.objects.filter(usage_event=current_usage_event).exists():
			return disable_tool_multi(request, tool_id, current_usage_event, dynamic_form)


	# Charge for consumables
	dynamic_form.charge_for_consumable(current_usage_event.user, current_usage_event.operator, current_usage_event.project, current_usage_event.run_data, current_usage_event)

	current_usage_event.updated = timezone.now()
	current_usage_event.save()

	if request.user.charging_staff_time():
		existing_staff_charge = request.user.get_staff_charge()
		if existing_staff_charge.customer == current_usage_event.user and existing_staff_charge.project == current_usage_event.project:
			return render(request, 'staff_charges/reminder.html', {'tool': tool})

	#return redirect(reverse('tool_control'))
	return render(request, 'tool_control/disable_confirmation.html', {'tool': tool})


@staff_member_required(login_url=None)
def disable_tool_multi(request, tool_id, usage_event, dynamic_form):
	# process request for multiple users and staff charges
	if not UsageEventProject.objects.filter(usage_event=usage_event).exists():
		tool = Tool.objects.get(id=tool_id)
		return HttpResponseBadRequest("Unable to find projects for {0} being run by {1}".format(str(tool), str(usage_event.operator)))

	uep = UsageEventProject.objects.filter(usage_event=usage_event)
	downtime = timedelta(minutes=quiet_int(request.POST.get('downtime')))
	tool = Tool.objects.get(id=tool_id)

	try:
		if uep.count() == 1:
			uep = UsageEventProject.objects.get(usage_event=usage_event)

			# set project_percent to 100
			uep.project_percent=100.0
			uep.updated = timezone.now()
			uep.save()

			# run dynamic form processing
			dynamic_form.charge_for_consumable(uep.customer, uep.usage_event.operator, uep.project, uep.usage_event.run_data, usage_event, 100.0)

			if request.user.charging_staff_time():
				existing_staff_charge = request.user.get_staff_charge()
				if existing_staff_charge.customers.all()[0] == usage_event.user and existing_staff_charge.projects.all()[0] == usage_event.project:
					response = render(request, 'staff_charges/reminder.html', {'tool': tool})
				elif existing_staff_charge.customer is None and existing_staff_charge.project is None:
					scp = StaffChargeProject.objects.get(staff_charge=existing_staff_charge, project=uep.project, customer=uep.customer)
					if scp is not None:
						response = render(request, 'staff_charges/reminder.html', {'tool': tool})
				else:
					response = render(request, 'staff_charges/general_reminder.html', { 'staff_charge': existing_staff_charge})

				return response

			else:
				return render(request, 'tool_control/disable_confirmation.html', {'tool': tool})
	
		else:
			# gather records and send to form for editing
			# first return event to active state to ensure proper completion of the details
			usage_event.end = None
			usage_event.updated = timezone.now()
			usage_event.save()

			params = {
				'usage_event': usage_event,
				'uep': uep,
				'tool_id': tool_id,
				'downtime': request.POST.get('downtime')
			}
			return render(request, 'tool_control/multiple_projects_finish.html', params)

	except StaffChargeProject.DoesNotExist:
		existing_staff_charge = request.user.get_staff_charge()
		return render(request, 'staff_charges/general_reminder.html', { 'staff_charge': existing_staff_charge})
	
@staff_member_required(login_url=None)
@require_POST
def usage_event_projects_save(request):
	msg = ''

	try:

		prc = 0.0
		usage_event_id = int(request.POST.get('usage_event_id'))
		event = UsageEvent.objects.get(id=usage_event_id)
		tool = event.tool
		downtime = timedelta(minutes=quiet_int(request.POST.get('downtime')))

		for key, value in request.POST.items():
			if is_valid_field(key):
				attribute, separator, uepid = key.partition("__")
				uepid = int(uepid)
				if not event.id:
					u = UsageEventProject.objects.filter(id=uepid)
					event = u[0].usage_event
					tool = event.tool

				if attribute == "project_percent":
					if value == '':
						msg = 'You must enter a numerical value for the percent to charge to a project'
						event.end=null
						event.updated = timezone.now()
						event.save()
						raise Exception()
					else:
						prc = prc + float(value)

		if int(prc) != 100:
			msg = 'Percent values must total to 100.0'
			event.end=null
			event.updated = timezone.now()
			event.save()
			raise Exception()

		dynamic_form = DynamicForm(tool.post_usage_questions)

		for key, value in request.POST.items():
			if is_valid_field(key):
				attribute, separator, uepid = key.partition("__")
				uepid = int(uepid)
				if attribute == "project_percent":
					uep = UsageEventProject.objects.get(id=uepid)
					uep.project_percent = value
					uep.updated = timezone.now()
					uep.save()
					dynamic_form.charge_for_consumable(uep.customer, event.operator, uep.project, event.run_data, event, value)

		event.end = timezone.now() + downtime
		event.updated = timezone.now()
		event.save()

		if request.user.charging_staff_time():
			existing_staff_charge = request.user.get_staff_charge()
			response = render(request, 'staff_charges/general_reminder.html', {'staff_charge': existing_staff_charge})
			return response

	except Exception as inst:
		if msg == '':
			return HttpResponseBadRequest(inst)
		else:
			return HttpResponseBadRequest(msg)

	return redirect(reverse('tool_control'))


@login_required
@require_GET
def past_comments_and_tasks(request):
	try:
		start, end = extract_times(request.GET)
	except:
		return HttpResponseBadRequest('Please enter a start and end date.')
	tool_id = request.GET.get('tool_id')
	try:
		tasks = Task.objects.filter(tool_id=tool_id, creation_time__gt=start, creation_time__lt=end)
		comments = Comment.objects.filter(tool_id=tool_id, creation_date__gt=start, creation_date__lt=end)
	except:
		return HttpResponseBadRequest('Task and comment lookup failed.')
	past = list(chain(tasks, comments))
	past.sort(key=lambda x: getattr(x, 'creation_time', None) or getattr(x, 'creation_date', None))
	past.reverse()
	dictionary = {
		'past': past,
	}
	return render(request, 'tool_control/past_tasks_and_comments.html', dictionary)


@login_required
@require_GET
def ten_most_recent_past_comments_and_tasks(request, tool_id):
	tasks = Task.objects.filter(tool_id=tool_id).order_by('-creation_time')[:10]
	comments = Comment.objects.filter(tool_id=tool_id).order_by('-creation_date')[:10]
	past = list(chain(tasks, comments))
	past.sort(key=lambda x: getattr(x, 'creation_time', None) or getattr(x, 'creation_date', None))
	past.reverse()
	past = past[0:10]
	dictionary = {
		'past': past,
	}
	return render(request, 'tool_control/past_tasks_and_comments.html', dictionary)


@login_required
@staff_member_required(login_url=None)
def create_usage_event(request):
	if request.user.core_ids.all().count() > 0:
		tools = Tool.objects.filter(core_id__in=request.user.core_ids.all())
	else:
		tools = Tool.objects.all()

	dictionary = {
		'tools': tools,
		'users': User.objects.filter(is_active=True, projects__active=True, projects__account__active=True).exclude(id=request.user.id).distinct(),
	}

	if request.user.is_superuser:
		operators = User.objects.filter(is_staff=True).order_by('last_name', 'first_name')
		dictionary['operators'] = operators

	return render(request, 'tool_control/ad_hoc_usage_event.html', dictionary)


@login_required
@require_POST
def save_usage_event(request):
	params = {}
	error_params = {}

	try:
		ad_hoc_start = request.POST.get('ad_hoc_start', None)
		if ad_hoc_start == '':
			ad_hoc_start = None
		else:
			error_params['ad_hoc_start'] = ad_hoc_start

		ad_hoc_end = request.POST.get('ad_hoc_end', None)
		if ad_hoc_end == '':
			ad_hoc_end = None
		else:
			error_params['ad_hoc_end'] = ad_hoc_end

		msg = ''

		if ad_hoc_start is None or ad_hoc_end is None:
			msg = 'The start date and end date are required to save an ad hoc usage event.'
			raise Exception(msg)

		ad_hoc_start = parse_datetime(ad_hoc_start)
		ad_hoc_end = parse_datetime(ad_hoc_end)

		if ad_hoc_start is None or ad_hoc_end is None:
			msg = 'The start date and end date are required to save an ad hoc usage event. The values must be valid datetimes.'
			raise Exception(msg)


		tool_id = request.POST.get('tool_select', None)
		if tool_id is None or tool_id == '':
			msg = 'A tool must be selected to create an ad hoc usage event.'
			raise Exception(msg)
		else:
			tool_id = int(tool_id)
			error_params['tool_id'] = tool_id

		tool = Tool.objects.get(id=tool_id)

		if request.user.is_superuser:
			operator_id = request.POST.get('operator', None)
			if operator_id is None or operator_id == '':
				msg = 'An operator must be selected for creating an ad hoc usage event.'
				raise Exception(msg)
			else:
				operator_id = int(operator_id)
				error_params['operator_id'] = operator_id

			operator = User.objects.get(id=operator_id)
		else:
			operator = request.user

		if UsageEvent.objects.filter(tool=tool, start__range=(ad_hoc_start, ad_hoc_end)).exists() or UsageEvent.objects.filter(tool=tool, end__range=(ad_hoc_start, ad_hoc_end)).exists() or UsageEvent.objects.filter(tool=tool, start__lte=ad_hoc_start, end__gte=ad_hoc_end).exists():
			msg = 'A usage event already exists that overlaps start = ' + str(ad_hoc_start) + ' and end = ' + str(ad_hoc_end) + ' for the ' + tool.name + '.  Please review your entries and either select new start and/or end times, or else speak with an administrator to help resolve the conflict.'
			error_params['usage_start_conflict'] = UsageEvent.objects.filter(tool=tool, start__range=(ad_hoc_start, ad_hoc_end))
			error_params['usage_end_conflict'] = UsageEvent.objects.filter(tool=tool, end__range=(ad_hoc_start, ad_hoc_end))
			error_params['usage_whole_conflict'] = UsageEvent.objects.filter(tool=tool, start__lte=ad_hoc_start, end__gte=ad_hoc_end)
			raise Exception(msg)

		new_usage_event = UsageEvent()
		new_usage_event.operator = operator
		new_usage_event.tool = tool
		new_usage_event.start = ad_hoc_start
		new_usage_event.end = ad_hoc_end
		project_id = request.POST.get("chosen_project__0", None)
		if project_id is not None and project_id != "":
			project_id = int(project_id)
			new_usage_event.project = Project.objects.get(id=project_id)
		user_id = request.POST.get("chosen_user__0", None)
		if user_id is not None and user_id != "":
			user_id = int(user_id)
			new_usage_event.user = User.objects.get(id=user_id)
		new_usage_event.created = timezone.now()
		new_usage_event.updated = timezone.now()
		new_usage_event.save()

		project_events = {}

		for key, value in request.POST.items():
			if is_valid_field(key):
				attribute, separator, index = key.partition("__")
				index = int(index)
				if index not in project_events:
					project_events[index] = UsageEventProject()
					project_events[index].usage_event = new_usage_event
					project_events[index].created = timezone.now()
					project_events[index].updated = timezone.now()
				if attribute == "chosen_user":
					if value is not None and value != "":
						project_events[index].customer = User.objects.get(id=value)
					else:
						new_usage_event.delete()
						return HttpResponseBadRequest('Please choose a user for whom the tool will be run.')
				if attribute == "chosen_project":
					if value is not None and value != "" and value != "-1":
						project_events[index].project = Project.objects.get(id=value)
					else:
						new_usage_event.delete()
						return HttpResponseBadRequest('Please choose a project for charges made during this run.')
				if attribute == "project_percent":
					if value is not None and value != "":
						project_events[index].project_percent = value
					else:
						new_usage_event.delete()
						return HttpResponseBadRequest('Please enter a project percent value')

		for p in project_events.values():
			p.full_clean()
			p.save()

		params['new_usage_event'] = new_usage_event
		params['uep'] = UsageEventProject.objects.filter(usage_event=new_usage_event)


	except Exception as inst:
		if request.user.core_ids.all().count() > 0:
			tools = Tool.objects.filter(core_id__in=request.user.core_ids.all())
		else:
			tools = Tool.objects.all()
		params['tools'] = tools

		if request.user.is_superuser:
			operators = User.objects.filter(is_staff=True).order_by('last_name', 'first_name')
			params['operators'] = operators
		params['users'] = User.objects.filter(is_active=True, projects__active=True, projects__account__active=True).exclude(id=request.user.id).distinct()

		if msg == '':
			params['error'] = inst
		else:
			params['error'] = msg

		for key, value in error_params.items():
			params[key] = value

		return render(request, 'tool_control/ad_hoc_usage_event.html', params)

	return render(request, 'tool_control/ad_hoc_usage_event_confirmation.html', params)

