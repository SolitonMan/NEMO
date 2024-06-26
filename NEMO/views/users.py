from datetime import timedelta
from http import HTTPStatus
from urllib.parse import urljoin
from logging import getLogger

import requests
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponseBadRequest, HttpResponseRedirect, JsonResponse, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from NEMO.admin import record_local_many_to_many_changes, record_active_state
from NEMO.forms import UserForm
from NEMO.models import Account, UserRelationship, UserRelationshipType, User, UserProfile, UserProfileSetting, Project, Tool, PhysicalAccessLevel, Reservation, StaffCharge, UsageEvent, AreaAccessRecord, ActivityHistory, ProbationaryQualifications, Sample


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

	if dictionary['identity_service_available']:
		try:
			result = requests.get(urljoin(settings.IDENTITY_SERVICE['url'], '/areas/'), timeout=3)
			if result.status_code == HTTPStatus.OK:
				dictionary['externally_managed_physical_access_levels'] = result.json()
			else:
				dictionary['identity_service_available'] = False
				warning_message = 'The identity service encountered a problem while attempting to return a list of externally managed areas. The NEMO administrator has been notified to resolve the problem.'
				dictionary['warning'] = warning_message
				warning_message += ' The HTTP error was {}: {}'.format(result.status_code, result.text)
				logger.error(warning_message)
		except Exception as e:
			dictionary['identity_service_available'] = False
			warning_message = 'There was a problem communicating with the identity service. NEMO is unable to retrieve the list of externally managed areas. The NEMO administrator has been notified to resolve the problem.'
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
					warning_message = 'The identity service encountered a problem while attempting to search for a user. The NEMO administrator has been notified to resolve the problem.'
					dictionary['warning'] = warning_message
					warning_message += ' The HTTP error was {}: {}'.format(result.status_code, result.text)
					logger.error(warning_message)
		except Exception as e:
			dictionary['identity_service_available'] = False
			warning_message = 'There was a problem communicating with the identity service. NEMO is unable to search for a user. The NEMO administrator has been notified to resolve the problem.'
			dictionary['warning'] = warning_message
			warning_message += ' An exception was encountered: ' + type(e).__name__ + ' - ' + str(e)
			logger.error(warning_message)

		pqd = {}
		probationary_qualifications = ProbationaryQualifications.objects.filter(user=user)
		for pq in probationary_qualifications:
			pqd[pq.tool.id] = pq.probationary_user
		dictionary['probationary_qualifications'] = pqd

		return render(request, 'users/create_or_modify_user.html', dictionary)
	elif request.method == 'POST':
		form = UserForm(request.POST, instance=user)
		dictionary['form'] = form
		if not form.is_valid():
			return render(request, 'users/create_or_modify_user.html', dictionary)

		# Remove the user account from the domain if it's deactivated, changed domain, or changed username...
		if dictionary['identity_service_available'] and user:
			no_longer_active = form.initial['is_active'] is True and form.cleaned_data['is_active'] is False
			domain_switched = form.initial['domain'] != '' and form.initial['domain'] != form.cleaned_data['domain']
			username_changed = form.initial['username'] != form.cleaned_data['username']
			if no_longer_active or domain_switched or username_changed:
				parameters = {
					'username': form.initial['username'],
					'domain': form.initial['domain'],
				}
				try:
					result = requests.delete(settings.IDENTITY_SERVICE['url'], data=parameters, timeout=3)
					# If the delete succeeds, or the user is not found, then everything is ok.
					if result.status_code not in (HTTPStatus.OK, HTTPStatus.NOT_FOUND):
						dictionary['identity_service_available'] = False
						logger.error('The identity service encountered a problem while attempting to delete a user. The HTTP error is {}: {}'.format(result.status_code, result.text))
						dictionary['warning'] = 'The user information was not modified because the identity service could not delete the corresponding domain account. The NEMO administrator has been notified to resolve the problem.'
						return render(request, 'users/create_or_modify_user.html', dictionary)
				except Exception as e:
					dictionary['identity_service_available'] = False
					logger.error('There was a problem communicating with the identity service while attempting to delete a user. An exception was encountered: ' + type(e).__name__ + ' - ' + str(e))
					dictionary['warning'] = 'The user information was not modified because the identity service could not delete the corresponding domain account. The NEMO administrator has been notified to resolve the problem.'
					return render(request, 'users/create_or_modify_user.html', dictionary)

		# Ensure the user account is added and configured correctly on the current domain if the user is active...
		if dictionary['identity_service_available'] and form.cleaned_data['is_active']:
			parameters = {
				'username': form.cleaned_data['username'],
				'domain': form.cleaned_data['domain'],
				'badge_number': form.cleaned_data.get('badge_number', ''),
				'email': form.cleaned_data.get('email'),
				'access_expiration': form.cleaned_data.get('access_expiration'),
				'requested_areas': request.POST.getlist('externally_managed_access_levels'),
			}
			try:
				if len(parameters['requested_areas']) > 0 and not parameters['badge_number']:
					dictionary['warning'] = 'A user must have a badge number in order to have area access. Please enter the badge number first, then grant access to areas.'
					return render(request, 'users/create_or_modify_user.html', dictionary)
				result = requests.put(settings.IDENTITY_SERVICE['url'], data=parameters, timeout=3)
				if result.status_code == HTTPStatus.NOT_FOUND:
					dictionary['warning'] = 'The username was not found on this domain. Did you spell the username correctly in this form and did you select the correct domain? Ensure the user exists on the domain in order to proceed.'
					return render(request, 'users/create_or_modify_user.html', dictionary)
				if result.status_code != HTTPStatus.OK:
					dictionary['identity_service_available'] = False
					logger.error('The identity service encountered a problem while attempting to modify a user. The HTTP error is {}: {}'.format(result.status_code, result.text))
					dictionary['warning'] = 'The user information was not modified because the identity service encountered a problem while creating the corresponding domain account. The NEMO administrator has been notified to resolve the problem.'
					return render(request, 'users/create_or_modify_user.html', dictionary)
			except Exception as e:
				dictionary['identity_service_available'] = False
				logger.error('There was a problem communicating with the identity service while attempting to modify a user. An exception was encountered: ' + type(e).__name__ + ' - ' + str(e))
				dictionary['warning'] = 'The user information was not modified because the identity service encountered a problem while creating the corresponding domain account. The NEMO administrator has been notified to resolve the problem.'
				return render(request, 'users/create_or_modify_user.html', dictionary)

		# Only save the user model for now, and wait to process the many-to-many relationships.
		# This way, many-to-many changes can be recorded.
		# See this web page for more information:
		# https://docs.djangoproject.com/en/dev/topics/forms/modelforms/#the-save-method
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
					dictionary['warning'] = 'The user information was not modified because the identity service could not delete the corresponding domain account. The NEMO administrator has been notified to resolve the problem.'
					return render(request, 'users/safe_deactivation.html', dictionary)
			except Exception as e:
				logger.error('There was a problem communicating with the identity service while attempting to delete a user. An exception was encountered: ' + type(e).__name__ + ' - ' + str(e))
				dictionary['warning'] = 'The user information was not modified because the identity service could not delete the corresponding domain account. The NEMO administrator has been notified to resolve the problem.'
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


