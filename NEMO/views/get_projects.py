from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET

from NEMO.models import User, Tool


@staff_member_required(login_url=None)
@require_GET
def get_projects(request):
	""" Gets a list of all active projects for a specific user. This is only accessible by staff members. """
	user = get_object_or_404(User, id=request.GET.get('user_id', None))
	projects = user.active_projects()
	source_template = request.GET.get('source_template')
	ad_hoc = request.GET.get('ad_hoc')
	if source_template == 'training':
		entry_number = int(request.GET['entry_number'])
		return render(request, 'training/get_projects.html', {'projects': projects, 'entry_number': entry_number})
	elif source_template == 'staff_charges':
		entry_number = int(request.GET['entry_number'])
		return render(request, 'staff_charges/get_projects.html', {'projects': projects, 'entry_number': entry_number, 'ad_hoc': ad_hoc})
	elif source_template == 'contest_transaction':
		entry_number = request.GET['entry_number']
		return render(request, 'get_projects.html', {'projects': projects, 'entry_number': entry_number})

	projects_out = []
	for p in projects:
		send_name = '[' + str(p.project_number) + ']' + str(p.name) + '[' + str(p.get_project()) + ']'
		projects_out.append({'id':p.id,'name':send_name})
	#return JsonResponse(dict(projects=list(projects.values('id', 'name', 'project_number'))))
	return JsonResponse(dict(projects=projects_out))


@staff_member_required(login_url=None)
@require_GET
def get_projects_for_tool_control(request):
	user_id = request.GET.get('user_id')
	user = get_object_or_404(User, id=user_id)
	return render(request, 'tool_control/get_projects.html', {'active_projects': user.active_projects(), 'user_id': user_id, 'my_reservation': None})


@login_required
@require_GET
def get_projects_for_self(request, tool_id=None):
	""" Gets a list of all active projects for the current user. """
	tool = get_object_or_404(Tool, id=tool_id)
	return render(request, 'tool_control/get_projects.html', {'active_projects': request.user.active_projects(), 'user_id': request.user.id, 'my_reservation': request.user.current_reservation_for_tool(tool)})
