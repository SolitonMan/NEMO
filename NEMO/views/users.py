import json
from datetime import timedelta
from http import HTTPStatus
from urllib.parse import urljoin
from logging import getLogger

import requests
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db.models import Q, OuterRef, Subquery
from django.http import HttpResponseBadRequest, HttpResponseRedirect, JsonResponse, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from NEMO.admin import record_local_many_to_many_changes, record_active_state
from NEMO.forms import UserForm, UserServiceRequestEditForm
from NEMO.models import Account, Core, UserRelationship, UserRelationshipType, User, UserProfile, UserProfileSetting, Project, Tool, PhysicalAccessLevel, Reservation, StaffCharge, UsageEvent, AreaAccessRecord, ActivityHistory, ProbationaryQualifications, Sample, UserRequirementProgress, Requirement, AreaRequirement, ToolRequirement, ServiceType, UserServiceRequest, ServiceTypeQuestion, UserServiceRequestAnswer
from NEMO.views.requirements_admin import get_status_icon, get_leaf_requirements

@staff_member_required(login_url=None)
@require_http_methods(['GET', 'POST'])
def users(request):

	if request.method == "GET":
		return render(request, 'users/users.html', {'users': None, 'page_count':0, 'use_form': True, })

	else:
		all_users = User.objects.order_by('last_name', 'first_name')

		search_string = request.POST.get('search',None)

		if search_string is not None:

			all_users = all_users.filter(Q(first_name__icontains=search_string) | Q(last_name__icontains=search_string) | Q(username__icontains=search_string) | Q(email__icontains=search_string))

		paginator = Paginator(all_users, 50)

		page_number = request.GET.get('page')

		if page_number is None:
			page_number = 1

		#all_users = paginator.get_page(page_number)

		page_count = paginator.num_pages

		return render(request, 'users/users.html', {'users': all_users, 'page_count':page_count, 'use_form': False, 'search_string': search_string})


@staff_member_required(login_url=None)
@require_http_methods(['GET', 'POST'])
def create_or_modify_user(request, user_id):
	logger = getLogger(__name__)
	if request.user.is_superuser:
		tools = Tool.objects.filter(visible=True)
	else:
		tools = Tool.objects.filter(visible=True, core_id__in=request.user.core_ids.all())
	dictionary = {
		'projects': Project.objects.filter(active=True),
		'tools': tools,
		'physical_access_levels': PhysicalAccessLevel.objects.all(),
		'one_year_from_now': timezone.now() + timedelta(days=365),
		'identity_service_available': settings.IDENTITY_SERVICE['available'],
		'identity_service_domains': settings.IDENTITY_SERVICE['domains'],
	}
	try:
		user = User.objects.get(id=user_id)
	except:
		user = None

	requirements = Requirement.objects.all()
	assigned_requirements = set(
		UserRequirementProgress.objects.filter(user=user).values_list('requirement_id', flat=True)
	)
	dictionary['requirements'] = requirements
	dictionary['assigned_requirements'] = assigned_requirements

	if dictionary['identity_service_available']:
		try:
			result = requests.get(urljoin(settings.IDENTITY_SERVICE['url'], '/areas/'), timeout=3)
			if result.status_code == HTTPStatus.OK:
				dictionary['externally_managed_physical_access_levels'] = result.json()
			else:
				dictionary['identity_service_available'] = False
				warning_message = 'The identity service encountered a problem while attempting to return a list of externally managed areas. The LEO administrator has been notified to resolve the problem.'
				dictionary['warning'] = warning_message
				warning_message += ' The HTTP error was {}: {}'.format(result.status_code, result.text)
				logger.error(warning_message)
		except Exception as e:
			dictionary['identity_service_available'] = False
			warning_message = 'There was a problem communicating with the identity service. LEO is unable to retrieve the list of externally managed areas. The LEO administrator has been notified to resolve the problem.'
			dictionary['warning'] = warning_message
			warning_message += ' An exception was encountered: ' + type(e).__name__ + ' - ' + str(e)
			logger.error(warning_message)
	else:
		dictionary['warning'] = 'The identity service is disabled. You will not be able to modify externally managed physical access levels, reset account passwords, or unlock accounts.'

	if request.method == 'GET':
		dictionary['form'] = UserForm(instance=user)
		dictionary['current_user'] = user
		try:
			if dictionary['identity_service_available'] and user and user.is_active and user.domain:
				parameters = {
					'username': user.username,
					'domain': user.domain,
				}
				result = requests.get(settings.IDENTITY_SERVICE['url'], parameters, timeout=3)
				if result.status_code == HTTPStatus.OK:
					dictionary['user_identity_information'] = result.json()
				elif result.status_code == HTTPStatus.NOT_FOUND:
					dictionary['warning'] = "The identity service could not find username {} on the {} domain. Does the user's account reside on a different domain? If so, select that domain now and save the user information.".format(user.username, user.domain)
				else:
					dictionary['identity_service_available'] = False
					warning_message = 'The identity service encountered a problem while attempting to search for a user. The LEO administrator has been notified to resolve the problem.'
					dictionary['warning'] = warning_message
					warning_message += ' The HTTP error was {}: {}'.format(result.status_code, result.text)
					logger.error(warning_message)
		except Exception as e:
			dictionary['identity_service_available'] = False
			warning_message = 'There was a problem communicating with the identity service. LEO is unable to search for a user. The LEO administrator has been notified to resolve the problem.'
			dictionary['warning'] = warning_message
			warning_message += ' An exception was encountered: ' + type(e).__name__ + ' - ' + str(e)
			logger.error(warning_message)

		probationary_qualifications = ProbationaryQualifications.objects.filter(user=user).order_by('tool__name')
		dictionary['probationary_qualifications'] = probationary_qualifications

		return render(request, 'users/create_or_modify_user.html', dictionary)
	elif request.method == 'POST':
		form = UserForm(request.POST, instance=user)
		dictionary['form'] = form
		if not form.is_valid():
			return render(request, 'users/create_or_modify_user.html', dictionary)

		# Only save the user model for now, and wait to process the many-to-many relationships.
		# This way, many-to-many changes can be recorded.
		# See this web page for more information:
		# https://docs.djangoproject.com/en/dev/topics/forms/modelforms/#the-save-method

		# Save assigned requirements
		req_ids = request.POST.getlist('requirements')
		# Remove unassigned
		UserRequirementProgress.objects.filter(user=user).exclude(requirement_id__in=req_ids).delete()
		# Add new assignments
		for req_id in req_ids:
			rqmt = Requirement.objects.get(id=req_id)
			urp, created = UserRequirementProgress.objects.get_or_create(user=user, requirement_id=req_id)
			if created:
				urp.updated = timezone.now()
				if rqmt.autocompleted:
					urp.status = 'completed'
				urp.save()

		user = form.save(commit=False)
		user.save()
		record_active_state(request, user, form, 'is_active', user_id == 'new')
		#record_local_many_to_many_changes(request, user, form, 'qualifications')
		record_local_many_to_many_changes(request, user, form, 'physical_access_levels')
		record_local_many_to_many_changes(request, user, form, 'projects')
		form.save_m2m()

		return redirect('users')
	else:
		return HttpResponseBadRequest('Invalid method')


@staff_member_required(login_url=None)
@require_http_methods(['GET', 'POST'])
def deactivate(request, user_id):
	logger = getLogger(__name__)
	dictionary = {
		'user_to_deactivate': get_object_or_404(User, id=user_id),
		'reservations': Reservation.objects.filter(user=user_id, cancelled=False, missed=False, end__gt=timezone.now()),
		'staff_charges': StaffCharge.objects.filter(customer=user_id, end=None, active_flag=True),
		'tool_usage': UsageEvent.objects.filter(user=user_id, end=None, active_flag=True).prefetch_related('tool'),
	}
	user_to_deactivate = dictionary['user_to_deactivate']
	if request.method == 'GET':
		return render(request, 'users/safe_deactivation.html', dictionary)
	elif request.method == 'POST':
		if settings.IDENTITY_SERVICE['available']:
			parameters = {
				'username': user_to_deactivate.username,
				'domain': user_to_deactivate.domain,
			}
			try:
				result = requests.delete(settings.IDENTITY_SERVICE['url'], data=parameters, timeout=3)
				# If the delete succeeds, or the user is not found, then everything is ok.
				if result.status_code not in (HTTPStatus.OK, HTTPStatus.NOT_FOUND):
					logger.error(f'The identity service encountered a problem while attempting to delete a user. The HTTP error is {result.status_code}: {result.text}')
					dictionary['warning'] = 'The user information was not modified because the identity service could not delete the corresponding domain account. The LEO administrator has been notified to resolve the problem.'
					return render(request, 'users/safe_deactivation.html', dictionary)
			except Exception as e:
				logger.error('There was a problem communicating with the identity service while attempting to delete a user. An exception was encountered: ' + type(e).__name__ + ' - ' + str(e))
				dictionary['warning'] = 'The user information was not modified because the identity service could not delete the corresponding domain account. The LEO administrator has been notified to resolve the problem.'
				return render(request, 'users/safe_deactivation.html', dictionary)

		if request.POST.get('cancel_reservations') == 'on':
			# Cancel all reservations that haven't ended
			for reservation in dictionary['reservations']:
				reservation.cancelled = True
				reservation.cancellation_time = timezone.now()
				reservation.cancelled_by = request.user
				reservation.save()
		if request.POST.get('disable_tools') == 'on':
			# End all current tool usage
			for usage_event in dictionary['tool_usage']:
				if usage_event.tool.interlock and not usage_event.tool.interlock.lock():
					error_message = f"The interlock command for the {usage_event.tool} failed. The error message returned: {usage_event.tool.interlock.most_recent_reply}"
					logger.error(error_message)
				usage_event.end = timezone.now()
				usage_event.save()
		if request.POST.get('force_area_logout') == 'on':
			area_access = user_to_deactivate.area_access_record()
			if area_access:
				area_access.end = timezone.now()
				area_access.save()
		if request.POST.get('end_staff_charges') == 'on':
			# End a staff charge that the user might be performing
			staff_charge = user_to_deactivate.get_staff_charge()
			if staff_charge:
				staff_charge.end = timezone.now()
				staff_charge.save()
				try:
					area_access = AreaAccessRecord.objects.get(staff_charge=staff_charge, end=None)
					area_access.end = timezone.now()
					area_access.save()
				except AreaAccessRecord.DoesNotExist:
					pass
			# End all staff charges that are being performed for the user
			for staff_charge in dictionary['staff_charges']:
				staff_charge.end = timezone.now()
				staff_charge.save()
				try:
					area_access = AreaAccessRecord.objects.get(staff_charge=staff_charge, end=None)
					area_access.end = timezone.now()
					area_access.save()
				except AreaAccessRecord.DoesNotExist:
					pass
		user_to_deactivate.is_active = False
		user_to_deactivate.save()
		activity_entry = ActivityHistory()
		activity_entry.authorizer = request.user
		activity_entry.action = ActivityHistory.Action.DEACTIVATED
		activity_entry.content_object = user_to_deactivate
		activity_entry.save()
		return redirect('users')


@staff_member_required(login_url=None)
@require_POST
def reset_password(request, user_id):
	try:
		user = get_object_or_404(User, id=user_id)
		result = requests.post(urljoin(settings.IDENTITY_SERVICE['url'], '/reset_password/'), {'username': user.username, 'domain': user.domain}, timeout=3)
		if result.status_code == HTTPStatus.OK:
			dictionary = {
				'title': 'Password reset',
				'heading': 'The account password was set to the default',
			}
		else:
			dictionary = {
				'title': 'Oops',
				'heading': 'There was a problem resetting the password',
				'content': 'The identity service returned HTTP error code {}. {}'.format(result.status_code, result.text),
			}
	except Exception as e:
		dictionary = {
			'title': 'Oops',
			'heading': 'There was a problem communicating with the identity service',
			'content': 'Exception caught: {}. {}'.format(type(e).__name__, str(e)),
		}
	return render(request, 'acknowledgement.html', dictionary)


@staff_member_required(login_url=None)
@require_POST
def unlock_account(request, user_id):
	try:
		user = get_object_or_404(User, id=user_id)
		result = requests.post(urljoin(settings.IDENTITY_SERVICE['url'], '/unlock_account/'), {'username': user.username, 'domain': user.domain}, timeout=3)
		if result.status_code == HTTPStatus.OK:
			dictionary = {
				'title': 'Account unlocked',
				'heading': 'The account is now unlocked',
			}
		else:
			dictionary = {
				'title': 'Oops',
				'heading': 'There was a problem unlocking the account',
				'content': 'The identity service returned HTTP error code {}. {}'.format(result.status_code, result.text),
			}
	except Exception as e:
		dictionary = {
			'title': 'Oops',
			'heading': 'There was a problem communicating with the identity service',
			'content': 'Exception caught: {}. {}'.format(type(e).__name__, str(e)),
		}
	return render(request, 'acknowledgement.html', dictionary)



@staff_member_required(login_url=None)
@require_GET
def delegates(request):
	users = []
	for u in User.objects.all():
		if Project.objects.filter(owner=u).exists():
			users.append(u.id)

	all_pis = User.objects.filter(id__in=users).order_by('last_name', 'first_name')

	return render(request, 'users/delegates.html', { 'pis': all_pis, 'users': User.objects.all(), })


@staff_member_required(login_url=None)
@require_POST
def delete_delegate(request, pi_id, delegate_id):
	pi = User.objects.get(id=pi_id)
	d = User.objects.get(id=delegate_id)
	pi.pi_delegates.remove(d)	

	return HttpResponse("Delegate deleted")


@staff_member_required(login_url=None)
@require_POST
def add_delegate(request, pi_id, delegate_id):
	d = User.objects.get(id=delegate_id)
	pi = User.objects.get(id=pi_id)
	pi.pi_delegates.add(d)
	data = {
		'delegate_first': d.first_name,
		'delegate_last': d.last_name,
		'delegate_id': d.id,
		'delegate_username': d.username,
		'pi_id': pi.id,
	}

	return JsonResponse(data)


@login_required
@require_http_methods(['GET', 'POST'])
def user_profile(request, user_id, msg=None):
	user = User.objects.get(id=user_id)

	if user != request.user:
		if not request.user.is_superuser:
			user = request.user
			msg = "You may only edit your own profile"

	user_profiles = UserProfile.objects.filter(user=user)
	profile_settings = UserProfileSetting.objects.all()

	profile = {}

	for p in profile_settings:
		key = str(user_id) + "_" + str(p.id)
		profile[key] = {
			"field_name": str(p.name),
			"field_title": str(p.title),
			"field_description": str(p.description), 
		}

		if user_profiles.filter(setting=p).exists():
			up = UserProfile.objects.get(user=user, setting=p)
			profile[key]["field_value"] = str(up.value)
		else:
			profile[key]["field_value"] = ""

		if p.setting_type in ("String","Integer","Float"):
			input_text = "<input type='text' class='form-control' name='" + str(p.name) + "' id='" + str(p.name) + "' value='" + profile[key]["field_value"] + "'>"
			profile[key]["input_text"] = mark_safe(input_text)

		if p.setting_type in ("Boolean"):
			val = profile[key]["field_value"]
			input_text = "<select class='form-control' name='" + str(p.name) + "' id='" + str(p.name) + "'>"
			input_text += "<option value='1'"
			if val != "":
				if int(val) == 1:
					input_text += " selected"
			input_text += ">Yes</option>"
			input_text += "<option value='0'"
			if val != "":
				if int(val) == 0:
					input_text += " selected"
			input_text += ">No</option>"
			input_text += "</select>"
			profile[key]["input_text"] = mark_safe(input_text)

	dictionary = {
		"profile_user": user,
		"profile": profile,
		"msg": msg,
	}

	return render(request, 'users/user_profile.html', dictionary)


@login_required
@require_POST
def save_user_profile(request):
	user_id = request.POST.get("user_id")
	user = User.objects.get(id=user_id)
	settings = UserProfileSetting.objects.all().values_list("name", flat=True)


	for key, value in request.POST.items():
		if key == "SHAREABLE_CALENDAR_LINK":
			request.user.user_shareable_calendar_link = value
			request.user.save()
		if key in settings:
			setting = UserProfileSetting.objects.get(name=key)
			if UserProfile.objects.filter(user=user, setting=setting).exists():
				profile = UserProfile.objects.get(user=user, setting=setting)
				profile.value = value
				profile.save()
			else:
				profile = UserProfile.objects.create(user=user, setting=setting, value=value)

	return user_profile(request, user_id, "User profile for " + str(user) + " had been successfully updated.")



@login_required
@require_POST
def get_samples(request):
	user_id = request.POST.get("user_id")
	user = User.objects.get(id=user_id)
	projects = user.all_projects()
	samples = user.sample_set.all()

	dictionary = {
		"user": user,
		"projects": projects,
		"samples": samples,
	}

	return render(request, 'users/add_sample.html', dictionary)


# Minimal, undecorated helper
def get_requirement_cores(requirement):
	cores = set()

	# Tool-based cores
	for tr in ToolRequirement.objects.filter(requirement=requirement).select_related('tool'):
		tool = tr.tool
		core_name = getattr(getattr(tool, 'core', None), 'name', None)
		if core_name:
			cores.add(core_name)

	# Area-based cores
	for ar in AreaRequirement.objects.filter(requirement=requirement).select_related('area'):
		area = ar.area
		core_name = getattr(getattr(area, 'core', None), 'name', None)
		if core_name:
			cores.add(core_name)

	# ServiceType-based cores
	# Query forward via ServiceType.requirements m2m; no reverse name guessing
	for st in ServiceType.objects.filter(requirements=requirement).select_related('core'):
		core_name = getattr(getattr(st, 'core', None), 'name', None)
		if core_name:
			cores.add(core_name)

	if not cores:
		cores.add('General')
	return cores


@login_required
@require_POST
def unmark_user_requirement(request):
	requirement_id = request.POST.get('requirement_id')
	if not requirement_id:
		return JsonResponse({'success': False, 'error': 'Missing requirement_id'}, status=400)

	try:
		progress = UserRequirementProgress.objects.get(user=request.user, requirement_id=requirement_id)
	except UserRequirementProgress.DoesNotExist:
		return JsonResponse({'success': False, 'error': 'Requirement progress not found'}, status=404)

	progress.status = 'not_started'
	progress.completed_on = None
	progress.expires_on = None
	progress.updated = None
	progress.save()
	return redirect('user_requests')


@login_required
@require_http_methods(['GET', 'POST'])
def user_requests(request):

	if request.method == 'POST':

		services = request.POST.getlist('service_select')
		projects = request.POST.getlist('project_select')
		descriptions = request.POST.getlist('description')
		training_requests = request.POST.getlist('training_requested')
		include__auto_include = request.POST.get('auto_include') == 'True'

		# Combine each set into a row
		rows = []
		for service, project, description, training_request in zip(services, projects, descriptions, training_requests):
			rows.append({
				'service': service,
				'project': project,
				'description': description,
				'training_request': training_request,
			})

			# insert into UserServiceRequest for each item
			svc = ServiceType.objects.get(id=service)
			proj = Project.objects.get(id=project)
			new_service = UserServiceRequest.objects.create(
				updated=timezone.now(),
				status='OPEN',
				description=description,
				core=svc.core,
				pi_user=proj.owner,
				project=proj,
				service_type=svc,
				user=request.user,
				training_request=training_request,
				owner=svc.principle_assignee.email,
				assignee=svc.principle_assignee
			)
				
			# Save dynamic question answers
			saved_answers = []
			for key, value in request.POST.items():
				if key.startswith('question_'):
					question_id = key.replace('question_', '')
					try:
						question = ServiceTypeQuestion.objects.get(id=question_id, is_active=True)
							
						# Handle multiselect (comes as multiple values)
						if question.field_type == 'multiselect':
							values = request.POST.getlist(key)
							answer_text = json.dumps(values)
						else:
							answer_text = value
							
						answer = UserServiceRequestAnswer.objects.create(
							user_service_request=new_service,
							question=question,
							answer_text=answer_text
						)
						saved_answers.append(answer)
							
					except ServiceTypeQuestion.DoesNotExist:
						continue

			# Send email notification to assignee
			if svc.principle_assignee and svc.principle_assignee.email and svc.core.name != 'Materials Characterization Lab (MCL)':
				send_mail(
					subject=f'New Service Request: {svc.name}',
					message=f'A new service request has been submitted by {request.user.get_full_name()}.\n\nService: {svc.name}\nProject: {proj.name}\nDescription: {description}',
					from_email=settings.SERVER_EMAIL,
					recipient_list=[svc.principle_assignee.email],
					fail_silently=True,
				)

			# Only add requirements and recursive requests if not MCL
			add_requirements_and_recursive_requests(new_service, request.user, svc, proj, description, training_request, include__auto_include)

		post_data = rows

	def is_recursive_requirement(requirement):
		# Returns True if this requirement is a recursive/placeholder
		return ServiceType.objects.filter(name=requirement.name, requirements__isnull=False).exclude(requirements=requirement).exists()

	requirement_names = set(Requirement.objects.values_list('name', flat=True))
	mcl_core = Core.objects.get(name='Materials Characterization Lab (MCL)')
	mcl_services = ServiceType.objects.filter(core=mcl_core, active=True).exclude(name__in=requirement_names).order_by('name')
	nano_core = Core.objects.get(name='Nanofabrication Facility')
	nano_services = ServiceType.objects.filter(core=nano_core, active=True).exclude(name__in=requirement_names).order_by('name')
	twodcc_core = Core.objects.get(name='2DCC')
	twodcc_services = ServiceType.objects.filter(core=twodcc_core, active=True).exclude(name__in=requirement_names).order_by('name')
	user_projects = request.user.active_projects

	owner_first_name_subquery = User.objects.filter(email=OuterRef('owner')).values('first_name')[:1]
	owner_last_name_subquery = User.objects.filter(email=OuterRef('owner')).values('last_name')[:1]

	user_service_requests = (
		UserServiceRequest.objects
		.filter(user=request.user, status='OPEN')
		.annotate(
			owner_first_name=Subquery(owner_first_name_subquery),
			owner_last_name=Subquery(owner_last_name_subquery)
		)
		.select_related('service_type', 'project', 'core', 'pi_user')
		.order_by('-updated')
	)

	# Exclude service requests that are for placeholder/recursive requirements
	placeholder_req_names = set(
		Requirement.objects.filter(
			name__in=ServiceType.objects.values_list('name', flat=True)
		).values_list('name', flat=True)
	)
	user_service_requests = user_service_requests.exclude(service_type__name__in=placeholder_req_names)

	# Build a set of placeholder requirement IDs for robust filtering
	placeholder_req_ids = set(
		Requirement.objects.filter(
			name__in=ServiceType.objects.values_list('name', flat=True)
		).values_list('id', flat=True)
	)

	# Build requirements/progress mapping
	request_requirements = {}
	for req in user_service_requests:
		# Get requirements for this service type
		requirements = req.service_type.requirements.all()
		leaf_requirements = []
		for r in requirements:
			leaf_requirements.extend(get_leaf_requirements(r))
		# Remove duplicates
		leaf_requirements = list({r.id: r for r in leaf_requirements}.values())
		req_list = []
		for r in leaf_requirements:
			if r.id in placeholder_req_ids:
				continue  # Skip placeholder requirements
			progress = UserRequirementProgress.objects.filter(user=request.user, requirement=r).first()
			req_list.append({
				'id': r.id,
				'name': r.name,
				'description': r.description,
				'has_progress': progress is not None,
				'status': progress.get_status_display() if progress else None,
				'resource_link_name': r.resource_link_name,
				'resource_link': r.resource_link,
				'expected_completion_time': r.expected_completion_time,
				'prerequisites': r.prerequisites,
				'auto_include': r.auto_include,
			})
		request_requirements[req.id] = req_list

	progress_list = (
		UserRequirementProgress.objects
		.filter(user=request.user)
		.select_related('requirement', 'service_request', 'service_request__service_type', 'service_request__tool')
		.order_by('requirement__name')
	)

	requirements_table = []
	for p in progress_list:
		# The main service request for this requirement (may be None)
		main_sr = p.service_request
		# All other service requests for this user that depend on this requirement
		other_srs = (
			UserServiceRequest.objects
			.filter(user=request.user, service_type__requirements=p.requirement)
			.exclude(id=main_sr.id if main_sr else None)
			.distinct()
		)
		if not ServiceType.objects.filter(name=p.requirement.name).exists():
			requirements_table.append({
				'id': p.requirement.id,
				'name': p.requirement.name,
				'description': p.requirement.description,
				'status': get_status_icon(p.status),
				'status_value': p.get_status_display(),
				'created': p.created,
				'completed_on': p.completed_on,
				'expected_completion_time': getattr(p.requirement, 'expected_completion_time', ''),
				'resource_link': getattr(p.requirement, 'resource_link', None),
				'resource_link_name': getattr(p.requirement, 'resource_link_name', None),
				'automated_update': getattr(p.requirement, 'automated_update', False),
				'prerequisites': getattr(p.requirement, 'prerequisites', False),
				'main_service_request': main_sr,
				'other_service_requests': list(other_srs),
			})

	def status_sort_key(status):
		# Lower value = higher priority
		if status == 'Not Started':
			return 0
		elif status == 'In Progress':
			return 1
		elif status == 'Completed':
			return 2
		return 3  # fallback for unknown

	requirements_table.sort(
		key=lambda r: (
			status_sort_key(r['status_value']),
			-(r['main_service_request'].updated.timestamp() if r['main_service_request'] and r['main_service_request'].updated else 0)
		)
	)

	force_requirements_redirect = request.session.pop('force_requirements_redirect', False)

	core_ids = ServiceType.objects.values_list('core_id', flat=True).distinct()
	cores = Core.objects.filter(id__in=core_ids)

	if request.device == 'mobile':
		return render(request, 'users/mobile_user_requests.html', {
			'cores': cores,
			'mcl_services': mcl_services,
			'mcl_core': mcl_core.id,
			'nano_services': nano_services,
			'nano_core': nano_core.id,
			'twodcc_services': twodcc_services,
			'twodcc_core': twodcc_core.id,
			'user_projects': user_projects,
			'user_service_requests': user_service_requests,
			'request_requirements': request_requirements,
			'requirements_table': requirements_table,
			'force_requirements_redirect': force_requirements_redirect,
		})
	else:
		return render(request, 'users/user_requests.html', {
			'cores': cores,
			'mcl_services': mcl_services,
			'mcl_core': mcl_core.id,
			'nano_services': nano_services,
			'nano_core': nano_core.id,
			'twodcc_services': twodcc_services,
			'twodcc_core': twodcc_core.id,
			'user_projects': user_projects,
			'user_service_requests': user_service_requests,
			'request_requirements': request_requirements,
			'requirements_table': requirements_table,
			'force_requirements_redirect': force_requirements_redirect,
		})

def add_requirements_and_recursive_requests(service, user, service_type, project, description, training_request, auto_include, processed_service_types=None):
	if processed_service_types is None:
		processed_service_types = set()
	# Prevent infinite recursion
	if service_type.id in processed_service_types:
		return
	processed_service_types.add(service_type.id)

	# Get requirements for this service type
	requirements = service_type.requirements.all()
	for requirement in requirements:
		if requirement.auto_include == auto_include or service_type.auto_include == auto_include:
			# Add requirement if not already present
			if not UserRequirementProgress.objects.filter(user=user, requirement=requirement).exists():
				status_value = 'not_started'
				if requirement.autocompleted:
					status_value = 'completed'
				UserRequirementProgress.objects.create(user=user, requirement=requirement, status=status_value, service_request=service, updated=timezone.now())
				# Check for ServiceType with same name as requirement
				matching_service_types = ServiceType.objects.filter(name=requirement.name, auto_include=auto_include)
				for matching_service_type in matching_service_types:
					# Check if user already has a request for this service type
					if not UserServiceRequest.objects.filter(user=user, service_type=matching_service_type).exists():
						# Recursively add request and requirements
						new_service = UserServiceRequest.objects.create(
							updated=timezone.now(),
							status='OPEN',
							description=f"Auto-generated request for requirement '{requirement.name}'",
							core=matching_service_type.core,
							pi_user=project.owner,
							project=project,
							service_type=matching_service_type,
							user=user,
							training_request=training_request,
							owner=matching_service_type.principle_assignee.email,
							assignee=matching_service_type.principle_assignee
						)
						add_requirements_and_recursive_requests(
							new_service, user, matching_service_type, project, description, training_request, auto_include, processed_service_types
						)


@login_required
def staff_service_requests(request):
	staff_user = request.user
	open_requests = UserServiceRequest.objects.filter(
		status__iexact='OPEN'
	).select_related('project', 'user', 'service_type', 'tool').exclude(
		service_type__name__in=Requirement.objects.values_list('name', flat=True)
	).order_by('-created')

	closed_requests = UserServiceRequest.objects.filter(
		status__iexact='CLOSED'
	).select_related('project', 'user', 'service_type', 'tool').exclude(
		service_type__name__in=Requirement.objects.values_list('name', flat=True)
	).order_by('-updated')[:5]

	placeholder_req_ids = set(
		Requirement.objects.filter(
			name__in=ServiceType.objects.values_list('name', flat=True)
		).values_list('id', flat=True)
	)

	request_requirements = {}
	for req in open_requests:
		# Get requirements for this service type
		requirements = req.service_type.requirements.all()
		leaf_requirements = []
		for r in requirements:
			leaf_requirements.extend(get_leaf_requirements(r))
		# Remove duplicates
		leaf_requirements = list({r.id: r for r in leaf_requirements}.values())
		req_list = []
		for r in leaf_requirements:
			if r.id in placeholder_req_ids:
				continue  # Skip placeholder requirements
			# FIXED: Changed from request.user to req.user (the service request owner)
			progress = UserRequirementProgress.objects.filter(user=req.user, requirement=r).first()
			req_list.append({
				'id': r.id,
				'name': r.name,
				'description': r.description,
				'has_progress': progress is not None,
				'status': progress.get_status_display() if progress else None,
				'resource_link_name': r.resource_link_name,
				'resource_link': r.resource_link,
				'expected_completion_time': r.expected_completion_time,
				'prerequisites': r.prerequisites,
				'automated_update': r.automated_update,  # Added this field
				'user_id': req.user.id,  # Added this field for the form
			})
		request_requirements[req.id] = req_list

	if request.method == 'POST':
		req_id = request.POST.get('request_id')
		action = request.POST.get('action')
		service_request = get_object_or_404(UserServiceRequest, id=req_id, assignee=staff_user)
		if action == 'resolve' and service_request.status == 'OPEN':
			service_request.status = 'CLOSED'
			service_request.updated = timezone.now()
			service_request.save()
		elif action == 'reopen' and service_request.status == 'CLOSED':
			service_request.status = 'OPEN'
			service_request.updated = timezone.now()
			service_request.save()
		return redirect('staff_service_requests')

	if request.device == 'mobile':
		return render(request, 'users/mobile_staff_service_requests.html', {
			'open_requests': open_requests,
			'closed_requests': closed_requests,
			'request_requirements': request_requirements,
		})
	else:
		return render(request, 'users/staff_service_requests.html', {
			'open_requests': open_requests,
			'closed_requests': closed_requests,
			'request_requirements': request_requirements,
		})

@login_required
def edit_service_request(request, pk):
	service_request = get_object_or_404(UserServiceRequest, pk=pk)
	user_projects = service_request.user.projects.all()
	tools = Tool.objects.filter(visible=True)
	staff_members = User.objects.filter(is_staff=True, is_active=True)

	if request.method == 'POST':
		form = UserServiceRequestEditForm(request.POST, instance=service_request, user_projects=user_projects, tools=tools, staff_members=staff_members)
		if form.is_valid():
			form.save()
			return redirect('staff_service_requests')
	else:
		form = UserServiceRequestEditForm(instance=service_request, user_projects=user_projects, tools=tools, staff_members=staff_members)

	return render(request, 'users/edit_service_request.html', {
		'form': form,
		'service_request': service_request,
	})


@login_required
@require_http_methods(['GET'])
def mobile_user_requirements(request):
	# Gather user requirement progress
	progress_list = (
		UserRequirementProgress.objects
		.filter(user=request.user)
		.select_related('requirement', 'service_request', 'service_request__service_type', 'service_request__tool')
		.order_by('requirement__name')
	)

	requirements_table = []
	for p in progress_list:
		main_sr = p.service_request
		other_srs = (
			UserServiceRequest.objects
			.filter(user=request.user, service_type__requirements=p.requirement)
			.exclude(id=main_sr.id if main_sr else None)
			.distinct()
		)
		requirements_table.append({
			'id': p.requirement.id,
			'name': p.requirement.name,
			'description': p.requirement.description,
			'status': p.status,
			'status_value': p.get_status_display(),
			'created': p.created,
			'completed_on': p.completed_on,
			'expected_completion_time': getattr(p.requirement, 'expected_completion_time', ''),
			'resource_link': getattr(p.requirement, 'resource_link', None),
			'resource_link_name': getattr(p.requirement, 'resource_link_name', None),
			'automated_update': getattr(p.requirement, 'automated_update', False),
			'prerequisites': getattr(p.requirement, 'prerequisites', False),
			'main_service_request': main_sr,
			'other_service_requests': list(other_srs),
		})

	return render(request, 'users/mobile_user_requirements.html', {
		'requirements_table': requirements_table,
	})


@login_required
def cancel_user_service_request(request, request_id):
	if request.method != "POST":
		return HttpResponseBadRequest("Invalid method")
	try:
		usr = UserServiceRequest.objects.get(pk=request_id)
		if usr.status == 'CANCELLED' or usr.status == 'CLOSED':
			return JsonResponse({'error': 'Request already cancelled or closed'}, status=400)
		usr.cancelled_by = request.user
		usr.cancellation_reason = request.POST.get('reason', '')
		usr.status = 'CANCELLED'
		usr.updated = timezone.now()
		usr.save()

		# notify assignee of cancellation
		if usr.assignee and usr.assignee.email:
			subject = f'Service Request Cancelled: {usr.service_type.name if usr.service_type else "N/A"}'
			service_name = usr.service_type.name if usr.service_type else 'N/A'
			user_name = request.user.get_full_name()
			reason = usr.cancellation_reason if usr.cancellation_reason else 'No reason provided'
			
			message = f"""Hello {usr.assignee.first_name},

A service request assigned to you has been cancelled by {user_name}.

Service: {service_name}
Requester: {usr.user.get_full_name()}
Project: {usr.project.name if usr.project else 'N/A'}
Cancellation Reason: {reason}

You can view more details in LEO.

Thank you,
LEO Admin Team"""
			
			send_mail(
				subject,
				message,
				settings.SERVER_EMAIL,
				[usr.assignee.email],
				fail_silently=True,
			)

		# Remove orphaned requirements that are only related to this cancelled request
		if usr.service_type:
			# Get all requirements associated with this cancelled service request
			cancelled_requirements = usr.service_type.requirements.all()
			
			# Get all other open service requests for this user
			other_open_requests = UserServiceRequest.objects.filter(
				user=usr.user,
				status='Open'
			).exclude(id=usr.id)
			
			# Build a set of requirement IDs that are still needed by other open requests
			needed_requirement_ids = set()
			for open_request in other_open_requests:
				if open_request.service_type:
					# Get all requirements (including nested/leaf requirements)
					for req in open_request.service_type.requirements.all():
						# Add the requirement itself
						needed_requirement_ids.add(req.id)
						# Get and add all leaf requirements (handles nested requirements)
						leaf_reqs = get_leaf_requirements(req)
						needed_requirement_ids.update(r.id for r in leaf_reqs)
			
			# Find and remove orphaned requirements
			for requirement in cancelled_requirements:
				# Check the requirement itself first
				if requirement.id not in needed_requirement_ids:
					# This requirement is not needed by any other open request
					UserRequirementProgress.objects.filter(
						user=usr.user,
						requirement=requirement,
						status__in=['not_started', 'in_progress']
					).delete()
				
				# Also check leaf requirements (in case this is a parent requirement)
				leaf_requirements = get_leaf_requirements(requirement)
				for leaf_req in leaf_requirements:
					if leaf_req.id not in needed_requirement_ids:
						# This leaf requirement is not needed by any other open request
						UserRequirementProgress.objects.filter(
							user=usr.user,
							requirement=leaf_req,
							status__in=['not_started', 'in_progress']
						).delete()

		return JsonResponse({'success': True})
	except UserServiceRequest.DoesNotExist:
		return JsonResponse({'error': 'Request not found'}, status=404)


@staff_member_required(login_url=None)
@require_http_methods(['GET', 'POST'])
def manage_user_requirements(request):
	"""
	Staff interface to override user requirement statuses in emergency situations.
	Allows staff to search for a user and mark requirements as complete/incomplete.
	"""
	selected_user = None
	requirements_list = []
	
	if request.method == 'POST':
		# Handle user search
		search_string = request.POST.get('search', None)
		
		if search_string:
			# Search for users
			all_users = User.objects.filter(
				Q(first_name__icontains=search_string) | 
				Q(last_name__icontains=search_string) | 
				Q(username__icontains=search_string) | 
				Q(email__icontains=search_string)
			).order_by('last_name', 'first_name')
			
			return render(request, 'users/manage_user_requirements.html', {
				'users': all_users,
				'search_string': search_string,
			})
	
	# Handle user selection
	user_id = request.GET.get('user_id')
	if user_id:
		selected_user = get_object_or_404(User, id=user_id)
		
		# Get all UserRequirementProgress records for this user
		progress_records = UserRequirementProgress.objects.filter(
			user=selected_user
		).select_related('requirement').order_by('requirement__name')
		
		# Build requirements list with status information
		for progress in progress_records:
			req = progress.requirement
			# Skip placeholder/recursive requirements  -  actually include them in this case for staff
			#if ServiceType.objects.filter(name=req.name).exists():
			#	continue
				
			requirements_list.append({
				'id': req.id,
				'name': req.name,
				'description': req.description,
				'status': progress.status,
				'status_display': progress.get_status_display(),
				'completed_on': progress.completed_on,
				'expires_on': progress.expires_on,
				'is_completed': progress.status == 'completed',
			})
	
	return render(request, 'users/manage_user_requirements.html', {
		'selected_user': selected_user,
		'requirements_list': requirements_list,
		'use_form': True,
	})


@staff_member_required(login_url=None)
@require_POST
def staff_complete_user_requirement(request):
	"""
	Staff override to mark a user's requirement as complete.
	"""
	requirement_id = request.POST.get('requirement_id')
	user_id = request.POST.get('user_id')
	
	if not requirement_id or not user_id:
		return HttpResponseBadRequest('Missing requirement_id or user_id')
	
	try:
		user = User.objects.get(id=user_id)
		requirement = Requirement.objects.get(id=requirement_id)
		progress = UserRequirementProgress.objects.get(user=user, requirement_id=requirement_id)
	except (User.DoesNotExist, Requirement.DoesNotExist, UserRequirementProgress.DoesNotExist) as e:
		return HttpResponseBadRequest(f'Invalid data: {str(e)}')
	
	# Mark as completed
	progress.status = 'completed'
	progress.completed_on = timezone.now()
	if requirement.retrain_interval_days and requirement.retrain_interval_days > 0:
		progress.expires_on = timezone.now() + timedelta(days=requirement.retrain_interval_days)
	progress.updated = timezone.now()
	progress.save()
	
	redirect_url = request.POST.get('redirect_url', reverse('staff_service_requests'))
	return HttpResponseRedirect(redirect_url)


@staff_member_required(login_url=None)
@require_POST
def staff_unmark_user_requirement(request):
	"""
	Staff override to unmark a user's requirement (set to not_started).
	"""
	requirement_id = request.POST.get('requirement_id')
	user_id = request.POST.get('user_id')
	
	if not requirement_id or not user_id:
		return HttpResponseBadRequest('Missing requirement_id or user_id')
	
	try:
		user = User.objects.get(id=user_id)
		progress = UserRequirementProgress.objects.get(user=user, requirement_id=requirement_id)
	except (User.DoesNotExist, UserRequirementProgress.DoesNotExist) as e:
		return HttpResponseBadRequest(f'Invalid data: {str(e)}')
	
	# Reset to not started
	progress.status = 'not_started'
	progress.completed_on = None
	progress.expires_on = None
	progress.updated = timezone.now()
	progress.save()
	
	redirect_url = request.POST.get('redirect_url', reverse('staff_service_requests'))
	return HttpResponseRedirect(redirect_url)

@login_required
def closed_user_service_requests(request):

	owner_first_name_subquery = User.objects.filter(email=OuterRef('owner')).values('first_name')[:1]
	owner_last_name_subquery = User.objects.filter(email=OuterRef('owner')).values('last_name')[:1]

	user_service_requests = (
		UserServiceRequest.objects
		.filter(user=request.user, status__in=('Closed','Cancelled','closed','cancelled'))
		.annotate(
			owner_first_name=Subquery(owner_first_name_subquery),
			owner_last_name=Subquery(owner_last_name_subquery)
		)
		.select_related('service_type', 'project', 'core', 'pi_user')
		.order_by('-updated')
	)

	# Exclude service requests that are for placeholder/recursive requirements
	placeholder_req_names = set(
		Requirement.objects.filter(
			name__in=ServiceType.objects.values_list('name', flat=True)
		).values_list('name', flat=True)
	)
	user_service_requests = user_service_requests.exclude(service_type__name__in=placeholder_req_names)

	if request.device == 'mobile':
		return render(request, 'users/mobile_user_requests_closed.html', {'user_service_requests': user_service_requests,})
	else:
		return render(request, 'users/user_requests_closed.html', {'user_service_requests': user_service_requests,})


@require_GET
@login_required
def get_service_type_questions(request, service_type_id):
	"""API endpoint to fetch dynamic questions for a service type"""
	try:
		# Get all active questions for this service type
		questions = ServiceTypeQuestion.objects.filter(
			service_type_id=service_type_id,
			is_active=True
		).select_related('parent_question').order_by('order')
		
		questions_data = []
		for q in questions:
			question_dict = {
				'id': q.id,
				'question_text': q.question_text,
				'field_name': q.field_name,
				'field_type': q.field_type,
				'order': q.order,
				'is_required': q.is_required,
				'help_text': q.help_text,
				'placeholder': q.placeholder,
				'choices': q.get_choices(),
				'validation_rules': q.validation_rules or {},
				'parent_question_id': q.parent_question_id,
				'parent_field_name': q.parent_question.field_name if q.parent_question else None,
				'trigger_value': q.trigger_value,
			}
			questions_data.append(question_dict)
		
		return JsonResponse({
			'success': True,
			'questions': questions_data,
			'count': len(questions_data)
		})
	
	except Exception as e:
		return JsonResponse({
			'success': False,
			'error': str(e)
		}, status=500)
