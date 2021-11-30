from urllib.parse import urljoin

import requests
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponseBadRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from NEMO.models import Tool, MembershipHistory, User, ProbationaryQualifications


@staff_member_required(login_url=None)
@require_GET
def qualifications(request):
	""" Present a web page to allow staff to qualify or disqualify users on particular tools. """
	users = User.objects.filter(is_active=True)
	tools = Tool.objects.filter(visible=True)
	return render(request, 'qualifications.html', {'users': users, 'tools': tools})


@staff_member_required(login_url=None)
@require_POST
def modify_qualifications(request):
	""" Change the tools that a set of users is qualified to use. """
	action = request.POST.get('action')
	if action != 'qualify' and action != 'disqualify':
		return HttpResponseBadRequest("You must specify that you are qualifying or disqualifying users.")
	users = request.POST.getlist('chosen_user[]') or request.POST.get('chosen_user') or []
	users = User.objects.in_bulk(users)

	if users == {}:
		return HttpResponseBadRequest("You must specify at least one user.")


	tools = request.POST.getlist('chosen_tool[]') or request.POST.get('chosen_tool') or []
	tools_full = request.POST.getlist('chosen_tools_full[]') or request.POST.get('chosen_tools_full') or []
	if tools_full == '' or tools_full is None:
		tools_full = []
	tools_prob = request.POST.getlist('chosen_tools_prob[]') or request.POST.get('chosen_tools_prob') or []
	if tools_prob == '' or tools_prob is None:
		tools_prob = []

#	tools = Tool.objects.in_bulk(tools)
#	if tools == {}:
#		return HttpResponseBadRequest("You must specify at least one tool.")

	
#	users = User.objects.in_bulk(users_full)
	for user in users.values():
		original_qualifications = set(user.qualifications.all())
		original_probationary_qualifications = set(user.probationary_qualifications.all())
		if action == 'qualify':
			try:
				tools = Tool.objects.in_bulk(tools_full)
				user.qualifications.add(*tools)

				for t in tools.values():
					pq = ProbationaryQualifications()
					pq.tool = t
					pq.user = user
					pq.probationary_user = False
					pq.qualification_date = timezone.now()
					pq.save()

			except: 
				pass

			try:
				# add probationary tool records and user qualified records
				tools = Tool.objects.in_bulk(tools_prob)
				user.qualifications.add(*tools)

				for t in tools.values():
					pq = ProbationaryQualifications()
					pq.tool = t
					pq.user = user
					pq.probationary_user = True
					pq.qualification_date = timezone.now()
					pq.save()

			except: 
				pass
				
			original_physical_access_levels = set(user.physical_access_levels.all())
			physical_access_level_automatic_enrollment = list(set([t.grant_physical_access_level_upon_qualification for t in tools.values() if t.grant_physical_access_level_upon_qualification]))
			user.physical_access_levels.add(*physical_access_level_automatic_enrollment)
			current_physical_access_levels = set(user.physical_access_levels.all())
			added_physical_access_levels = set(current_physical_access_levels) - set(original_physical_access_levels)
			for access_level in added_physical_access_levels:
				entry = MembershipHistory()
				entry.authorizer = request.user
				entry.parent_content_object = access_level
				entry.child_content_object = user
				entry.action = entry.Action.ADDED
				entry.save()
			if settings.IDENTITY_SERVICE['available']:
				for t in tools:
					tool = Tool.objects.get(id=t)
					if tool.grant_badge_reader_access_upon_qualification:
						parameters = {
							'username': user.username,
							'domain': user.domain,
							'requested_area': tool.grant_badge_reader_access_upon_qualification,
						}
						requests.put(urljoin(settings.IDENTITY_SERVICE['url'], '/add/'), data=parameters, timeout=3)
		elif action == 'disqualify':
			user.qualifications.remove(*tools)
			user.probationary_qualifications.remove(*tools)
		current_qualifications = set(user.qualifications.all())
		# Record the qualification changes for each tool:
		added_qualifications = set(current_qualifications) - set(original_qualifications)
		for tool in added_qualifications:
			entry = MembershipHistory()
			entry.authorizer = request.user
			entry.parent_content_object = tool
			entry.child_content_object = user
			entry.action = entry.Action.ADDED
			entry.save()
		removed_qualifications = set(original_qualifications) - set(current_qualifications)
		for tool in removed_qualifications:
			entry = MembershipHistory()
			entry.authorizer = request.user
			entry.parent_content_object = tool
			entry.child_content_object = user
			entry.action = entry.Action.REMOVED
			entry.save()

	if request.POST.get('redirect') == 'true':
		dictionary = {
			'title': 'Success!',
			'heading': 'Success!',
			'content': 'Tool qualifications were successfully modified.',
		}
		return render(request, 'acknowledgement.html', dictionary)
	else:
		return HttpResponse()


@staff_member_required(login_url=None)
@require_GET
def get_qualified_users(request):
	tool = get_object_or_404(Tool, id=request.GET.get('tool_id'))
	users = User.objects.filter(is_active=True)
	dictionary = {
		'tool': tool,
		'users': users,
		'expanded': True
	}
	return render(request, 'tool_control/qualified_users.html', dictionary)
