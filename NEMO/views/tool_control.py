from re import search

import requests

from copy import deepcopy
from datetime import timedelta
from http import HTTPStatus
from itertools import chain

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseNotFound, HttpResponseServerError, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import logger, require_GET, require_POST
from django.utils.html import escape
from django.utils.safestring import mark_safe

from NEMO.forms import CommentForm, nice_errors
from NEMO.models import AreaAccessRecord, AreaAccessRecordProject, Comment, Configuration, ConfigurationHistory, Project, Reservation, StaffCharge, StaffChargeProject, Task, TaskCategory, TaskStatus, Tool, UsageEvent, UsageEventProject, User
from NEMO.utilities import extract_times, quiet_int
from NEMO.views.policy import check_policy_to_disable_tool, check_policy_to_enable_tool, check_policy_to_enable_tool_for_multi
from NEMO.widgets.dynamic_form import DynamicForm
from NEMO.widgets.tool_tree import ToolTree


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
		tools = tools.filter(core_id__in=request.user.core_ids.all()).order_by('category', 'name')
		ctools = ctools.filter(core_id__in=request.user.core_ids.all()).order_by('category', 'name')

	# create searchable names for tools that include the category
	categorized_tools = "["
	for t in ctools:
		categorized_tools += '{{"name":"{0}", "id":{1}}},'.format(escape(str(t.category))+"/"+escape(str(t.name)), t.id)
	categorized_tools = categorized_tools.rstrip(",") + "]"
	categorized_tools = mark_safe(categorized_tools)

	users = User.objects.filter(is_active=True).exclude(id=request.user.id)

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
		'rendered_configuration_html': tool.configuration_widget(request.user),
		'mobile': request.device == 'mobile',
		'task_statuses': TaskStatus.objects.all(),
		'post_usage_questions': DynamicForm(tool.post_usage_questions).render(),
	}

	try:
		current_reservation = Reservation.objects.get(start__lt=timezone.now(), end__gt=timezone.now(), cancelled=False, missed=False, shortened=False, user=request.user, tool=tool)
		if request.user == current_reservation.user:
			dictionary['time_left'] = current_reservation.end
	except Reservation.DoesNotExist:
		pass

	# Staff need the user list to be able to qualify users for the tool.
	if request.user.is_staff:
		dictionary['users'] = User.objects.filter(is_active=True)

	return render(request, 'tool_control/tool_status.html', dictionary)


@staff_member_required(login_url=None)
@require_GET
def use_tool_for_other(request, entry_number):
	dictionary = {
		'users': User.objects.filter(is_active=True).exclude(id=request.user.id),
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

	# Create a new usage event to track how long the user uses the tool.
	new_usage_event = UsageEvent()
	new_usage_event.operator = operator
	new_usage_event.user = user
	new_usage_event.project = project
	new_usage_event.tool = tool
	new_usage_event.save()

	if staff_charge:
		new_staff_charge = StaffCharge()
		new_staff_charge.staff_member = request.user
		new_staff_charge.customer = user
		new_staff_charge.project = project
		new_staff_charge.save()

	if tool.requires_area_access and AreaAccessRecord.objects.filter(area=tool.requires_area_access,customer=operator,end=None).count() == 0:
		aar = AreaAccessRecord()
		aar.area = tool.requires_area_access
		aar.customer = operator
		aar.project = project
		aar.start = timezone.now()

		if staff_charge:
			aar.staff_charge = new_staff_charge

		aar.save()

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

	# initiate a UsageEvent
	new_usage_event = UsageEvent()
	new_usage_event.operator = operator
	new_usage_event.tool = tool
	new_usage_event.save()	

	project_events = {}

	for key, value in request.POST.items():
		if is_valid_field(key):
			attribute, separator, index = key.partition("__")
			index = int(index)
			if index not in project_events:
				project_events[index] = UsageEventProject()
				project_events[index].usage_event = new_usage_event
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
		new_staff_charge = request.user.get_staff_charge()
	else:
		new_staff_charge = StaffCharge()
		new_staff_charge.staff_member = request.user
		new_staff_charge.save()

	project_charges = {}

	for key, value in request.POST.items():
		if is_valid_field(key):
			attribute, separator, index = key.partition("__")
			index = int(index)
			if index not in project_charges:
				project_charges[index] = StaffChargeProject()
				project_charges[index].staff_charge = new_staff_charge
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
		 
#	if tool.requires_area_access and AreaAccessRecord.objects.filter(area=tool.requires_area_access,customer=operator,end=None).count() == 0:
#		aar = AreaAccessRecord()
#		aar.area = tool.requires_area_access
#		aar.customer = operator
#		aar.project = project
#		aar.start = timezone.now()

#		if staff_charge:
#			aar.staff_charge = new_staff_charge

#		aar.save()


	return response


def is_valid_field(field):
	return search("^(chosen_user|chosen_project|project_percent)__[0-9]+$", field) is not None


@staff_member_required(login_url=None)
@require_GET
def usage_event_entry(request):
	entry_number = int(request.GET['entry_number'])
	return render(request, 'tool_control/usage_event_entry.html', {'entry_number': entry_number})


@login_required
@require_POST
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
			new_reservation.save()
			current_reservation.shortened = True
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

	if current_usage_event.project is None and current_usage_event.user is None:
		# multi user event possibility, check
		if UsageEventProject.objects.filter(usage_event=current_usage_event.id).count() > 0:
			return disable_tool_multi(request, tool_id, current_usage_event)


	# Collect post-usage questions
	dynamic_form = DynamicForm(tool.post_usage_questions)
	current_usage_event.run_data = dynamic_form.extract(request)
	dynamic_form.charge_for_consumable(current_usage_event.user, current_usage_event.operator, current_usage_event.project, current_usage_event.run_data)

	current_usage_event.save()
	if request.user.charging_staff_time():
		existing_staff_charge = request.user.get_staff_charge()
		if existing_staff_charge.customer == current_usage_event.user and existing_staff_charge.project == current_usage_event.project:
			response = render(request, 'staff_charges/reminder.html', {'tool': tool})

	return response


@staff_member_required(login_url=None)
def disable_tool_multi(request, tool_id, usage_event):
	# process request for multiple users and staff charges
	uep = UsageEventProject.objects.filter(usage_event=usage_event.id)
	downtime = timedelta(minutes=quiet_int(request.POST.get('downtime')))

	if uep.count() == 1:
		# set project_percent to 100
		uep.update(project_percent=100.0)
		usage_event.end = timezone.now() + downtime
		
	else:
		# gather records and send to form for editing
		params = {
			'usage_event': usage_event,
			'uep': uep,
			'tool_id': tool_id,
		}
		response = render(request, 'tool_control/multiple_projects_finish.html', params)

	return response

	
@staff_member_required(login_url=None)
def usage_event_projects_save(request):
	

	return response

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
