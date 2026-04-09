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
	action = request.POST.get('action')
	if action not in ['qualify', 'disqualify']:
		return HttpResponseBadRequest("You must specify that you are qualifying or disqualifying users.")

	users = request.POST.getlist('chosen_user[]') or request.POST.get('chosen_user') or []
	users = User.objects.in_bulk(users)
	if not users:
		return HttpResponseBadRequest("You must specify at least one user.")

	tools = request.POST.getlist('chosen_tool[]') or request.POST.get('chosen_tool') or []
	tools_full = request.POST.getlist('chosen_tools_full[]') or request.POST.get('chosen_tools_full') or []
	if not tools_full or tools_full == ['']:
		tools_full = []
	tools_prob = request.POST.getlist('chosen_tools_prob[]') or request.POST.get('chosen_tools_prob') or []
	if not tools_prob or tools_prob == ['']:
		tools_prob = []

	for user in users.values():
		original_qualifications = set(
			ProbationaryQualifications.objects.filter(user=user, disabled=False).values_list('tool', flat=True)
		)

		if action == 'qualify':
			# Qualify for all selected tools (generic, full, probationary)
			for tool_id in tools:
				tool = Tool.objects.get(pk=tool_id)
				pq, created = ProbationaryQualifications.objects.get_or_create(user=user, tool=tool)
				if pq.disabled:
					pq.disabled = False
				pq.qualification_date = timezone.now()
				pq.save()

			for tool_id in tools_full:
				tool = Tool.objects.get(pk=tool_id)
				pq, created = ProbationaryQualifications.objects.get_or_create(user=user, tool=tool)
				pq.probationary_user = False
				pq.disabled = False
				pq.qualification_date = timezone.now()
				pq.save()

			for tool_id in tools_prob:
				tool = Tool.objects.get(pk=tool_id)
				pq, created = ProbationaryQualifications.objects.get_or_create(user=user, tool=tool)
				pq.probationary_user = True
				pq.disabled = False
				pq.qualification_date = timezone.now()
				pq.save()

			# Physical access logic (unchanged)
			original_physical_access_levels = set(user.physical_access_levels.all())
			tool_ids = tools + tools_full + tools_prob
			tool_objs = Tool.objects.in_bulk(tool_ids)
			physical_access_level_automatic_enrollment = [
				t.grant_physical_access_level_upon_qualification
				for t in tool_objs.values()
				if t.grant_physical_access_level_upon_qualification and
				t.grant_physical_access_level_upon_qualification not in user.physical_access_levels.all()
			]
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

		elif action == 'disqualify':
			# Disqualify for all selected tools (generic, full, probationary)
			for tool_id in tools + tools_full + tools_prob:
				try:
					tool = Tool.objects.get(pk=tool_id)
					pq = ProbationaryQualifications.objects.get(user=user, tool=tool)
					pq.disabled = True
					pq.save()
				except ProbationaryQualifications.DoesNotExist:
					continue

		# Track changes for MembershipHistory
		current_qualifications = set(
			ProbationaryQualifications.objects.filter(user=user, disabled=False).values_list('tool', flat=True)
		)
		added_qualifications = current_qualifications - original_qualifications
		for tool_id in added_qualifications:
			tool = Tool.objects.get(pk=tool_id)
			entry = MembershipHistory()
			entry.authorizer = request.user
			entry.parent_content_object = tool
			entry.child_content_object = user
			entry.action = entry.Action.ADDED
			entry.save()
		removed_qualifications = original_qualifications - current_qualifications
		for tool_id in removed_qualifications:
			tool = Tool.objects.get(pk=tool_id)
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
	probationary_qualifications = ProbationaryQualifications.objects.filter(tool=tool)
	pqd = {}
	for pq in probationary_qualifications:
		pqd[pq.user.id] = pq.probationary_user

	dictionary = {
		'tool': tool,
		'users': users,
		'expanded': True,
		'probationary_qualifications': pqd,
	}
	return render(request, 'tool_control/qualified_users.html', dictionary)


@staff_member_required(login_url=None)
@require_GET
def promote_user(request, user_id, tool_id):
	user = User.objects.get(id=user_id)
	tool = Tool.objects.get(id=tool_id)
	pq = ProbationaryQualifications.objects.get(tool=tool,user=user)
	pq.probationary_user = False
	pq.qualification_date = timezone.now()
	pq.save()
	return HttpResponse()

@staff_member_required(login_url=None)
@require_GET
def demote_user(request, user_id, tool_id):
	user = User.objects.get(id=user_id)
	tool = Tool.objects.get(id=tool_id)
	pq = ProbationaryQualifications.objects.get(tool=tool,user=user)
	pq.probationary_user = True
	pq.save()
	return HttpResponse()
