from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from NEMO.decorators import disable_session_expiry_refresh
from NEMO.models import Area, AreaAccessRecord, Resource, ScheduledOutage, Task, Tool, UsageEvent


@login_required
@require_GET
@disable_session_expiry_refresh
def status_dashboard(request):
	"""
	Present a web page to allow users to view the status and usage of all tools.
	"""
	interest = request.GET.get('interest')
	if interest is None:
		dictionary = {
			'tool_summary': create_tool_summary(request),
			'nanofab_occupants': AreaAccessRecord.objects.filter(end=None, staff_charge=None, active_flag=True).prefetch_related('customer', 'project', 'area'),
			'user_current_logins': request.user.in_area()
		}
		if request.user.is_superuser:
			areas = Area.objects.all()

		elif request.user.is_staff:
			areas = Area.objects.filter(core_id__in=request.user.core_ids.all())

		else:
			areas = Area.objects.filter(id__lt=0)

		dictionary['areas'] = areas


		return render(request, 'status_dashboard/status_dashboard.html', dictionary)
	elif interest == "tools":
		dictionary = {
			'tool_summary': create_tool_summary(request),
		}
		return render(request, 'status_dashboard/tools.html', dictionary)
	elif interest == "occupancy":
		dictionary = {
			'nanofab_occupants': AreaAccessRecord.objects.filter(end=None, staff_charge=None, active_flag=True).prefetch_related('customer', 'project', 'area'),
		}
		return render(request, 'status_dashboard/occupancy.html', dictionary)


def create_tool_summary(request):
	tools = Tool.objects.filter(visible=True)
	tasks = Task.objects.filter(cancelled=False, resolved=False, tool__visible=True).prefetch_related('tool')
	unavailable_resources = Resource.objects.filter(available=False).prefetch_related('fully_dependent_tools', 'partially_dependent_tools')
	usage_events = UsageEvent.objects.filter(end=None, tool__visible=True, active_flag=True).prefetch_related('operator', 'user', 'tool')
	scheduled_outages = ScheduledOutage.objects.filter(start__lte=timezone.now(), end__gt=timezone.now())
	tool_summary = merge(request, tools, tasks, unavailable_resources, usage_events, scheduled_outages)
	tool_summary = list(tool_summary.values())
	tool_summary.sort(key=lambda x: x['name'])
	return tool_summary


def merge(request, tools, tasks, unavailable_resources, usage_events, scheduled_outages):
	result = {}
	tools_with_delayed_logoff_in_effect = [x.tool.id for x in UsageEvent.objects.filter(end__gt=timezone.now(), active_flag=True)]
	for tool in tools:
		result[tool.id] = {
			'name': tool.name,
			'id': tool.id,
			'user': '',
			'operator': '',
			'in_use': False,
			'in_use_since': '',
			'delayed_logoff_in_progress': tool.id in tools_with_delayed_logoff_in_effect,
			'problematic': False,
			'operational': tool.operational,
			'required_resource_is_unavailable': False,
			'nonrequired_resource_is_unavailable': False,
			'scheduled_outage': False,
			'include_force_logout': False,
			'allow_force_logoff': True,
		}
	for task in tasks:
		result[task.tool.id]['problematic'] = True
	for event in usage_events:
		result[event.tool.id]['operator'] = str(event.operator)
		result[event.tool.id]['user'] = str(event.operator)
		if event.user != event.operator:
			if event.usageeventproject_set.count() == 1:
				for u in event.usageeventproject_set.all():
					result[event.tool.id]['user'] += " on behalf of " + str(u.customer)
				if request.user.is_staff:
					result[event.tool.id]['include_force_logout'] = True
			else:
				result[event.tool.id]['user'] += " on behalf of multiple customers"
				result[event.tool.id]['allow_force_logoff'] = False
		else:
			if request.user.is_staff:
				result[event.tool.id]['include_force_logout'] = True
		result[event.tool.id]['in_use'] = True
		result[event.tool.id]['in_use_since'] = event.start
	for resource in unavailable_resources:
		for tool in resource.fully_dependent_tools.filter(visible=True):
			result[tool.id]['required_resource_is_unavailable'] = True
		for tool in resource.partially_dependent_tools.filter(visible=True):
			result[tool.id]['nonrequired_resource_is_unavailable'] = True
	for outage in scheduled_outages:
		if outage.tool_id and outage.tool.visible:
			result[outage.tool.id]['scheduled_outage'] = True
		elif outage.resource_id:
			for t in outage.resource.fully_dependent_tools.filter(visible=True):
				result[t.id]['scheduled_outage'] = True
	return result


@login_required
@require_GET
@disable_session_expiry_refresh
def occupancy(request):
	area = request.GET.get('occupancy')
	if area is None or not Area.objects.filter(name=area).exists():
		return HttpResponse()
	dictionary = {
		'area': area,
		'occupants': AreaAccessRecord.objects.filter(area__name=area, end=None, staff_charge=None, active_flag=True).prefetch_related('customer'),
	}
	return render(request, 'occupancy.html', dictionary)
