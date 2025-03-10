from datetime import date, timedelta
from time import sleep

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.http import urlencode
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from NEMO.models import Area, AreaAccessRecord, AreaAccessRecordProject, Door, PhysicalAccessLog, PhysicalAccessType, Project, Sample, StaffCharge, StaffChargeProject, UsageEvent, UsageEventProject, User, UserProfile, UserProfileSetting
from NEMO.tasks import postpone
from NEMO.utilities import parse_start_and_end_date
from NEMO.views.customization import get_customization
from NEMO.views.staff_charges import get_billing_date_range


@require_GET
def save_aa_customer_comment(request):
	aarp_id = int(request.GET['aarp_id'])
	aarp = AreaAccessRecordProject.objects.get(id=aarp_id)
	aarp.comment = request.GET['comment']
	aarp.updated = timezone.now()
	aarp.save()
	return HttpResponse()


@staff_member_required(login_url=None)
@require_GET
def area_access(request):
	""" Presents a page that displays audit records for all laboratory areas. """
	today = timezone.now().strftime('%m/%d/%Y')
	yesterday = (timezone.now() - timedelta(days=1)).strftime('%m/%d/%Y')
	dictionary = {
		'today': reverse('area_access') + '?' + urlencode({'start': today, 'end': today}),
		'yesterday': reverse('area_access') + '?' + urlencode({'start': yesterday, 'end': yesterday}),
	}
	try:
		start, end = parse_start_and_end_date(request.GET['start'], request.GET['end'])
		dictionary['start'] = start
		dictionary['end'] = end
		dictionary['access_records'] = AreaAccessRecord.objects.filter(start__gte=start, start__lt=end, staff_charge=None, active_flag=True)
	except:
		pass
	return render(request, 'area_access/area_access.html', dictionary)


@login_required
@permission_required('NEMO.add_areaaccessrecord')
@require_GET
def welcome_screen(request, door_id=None, area_id=None):
	if door_id is not None and door_id != 0:
		door = get_object_or_404(Door, id=door_id)
		area = door.area
	if area_id is not None:
		area = get_object_or_404(Area, id=area_id)

	return render(request, 'area_access/welcome_screen.html', {'area': area, 'door': door})


@login_required
@permission_required('NEMO.change_areaaccessrecord')
@require_GET
def farewell_screen(request, door_id=None, area_id=None):
	if door_id is not None and door_id != 0:
		door = get_object_or_404(Door, id=door_id)
		area = door.area
	if area_id is not None:
		area = get_object_or_404(Area, id=area_id)

	return render(request, 'area_access/farewell_screen.html', {'area': area, 'door': door})


@login_required
@permission_required('NEMO.add_areaaccessrecord')
@require_POST
def login_to_area(request, door_id=None, area_id=None):
	if door_id is not None and door_id != 0:
		door = get_object_or_404(Door, id=door_id)
		area = door.area
	if area_id is not None and area_id != 0:
		area = get_object_or_404(Area, id=area_id)

	badge_number = request.POST.get('badge_number', '')
	if badge_number == '':
		return render(request, 'area_access/badge_not_found.html')
	try:
		badge_number = int(badge_number)
		user = User.objects.get(badge_number=badge_number)
	except (User.DoesNotExist, ValueError):
		return render(request, 'area_access/badge_not_found.html')

	log = PhysicalAccessLog()
	log.user = user
	if door_id is not None and door_id != 0:
		log.door = door
		log.area = door.area
	if area_id is not None and area_id != 0:
		log.area = area
	log.time = timezone.now()
	log.result = PhysicalAccessType.DENY  # Assume the user does not have access

	# Check if the user is active
	if not user.is_active:
		log.details = "This user is not active, preventing them from entering any access controlled areas."
		log.save()
		return render(request, 'area_access/inactive.html')

	# Check if the user has any physical access levels
	if not user.physical_access_levels.all().exists():
		log.details = "This user does not belong to ANY physical access levels."
		log.save()
		message = "You have not been granted physical access to any laboratory area. Please visit the User Office if you believe this is an error."
		return render(request, 'area_access/physical_access_denied.html', {'message': message})

	# Check if the user normally has access to this door at the current time
	if not any([access_level.accessible() for access_level in user.physical_access_levels.filter(area=area)]):
		log.details = "This user is not assigned to a physical access level that allows access to this door at this time."
		log.save()
		message = "You do not have access to this area of the laboratory at this time. Please visit the User Office if you believe this is an error."
		return render(request, 'area_access/physical_access_denied.html', {'message': message})

	# Check that the user's physical access has not expired
	if user.access_expiration is not None and user.access_expiration < date.today():
		log.details = "This user was blocked from this physical access level because their physical access has expired."
		log.save()
		message = "Your physical access to the laboratory has expired. Have you completed your safety training within the last year? Please visit the User Office to renew your access."
		return render(request, 'area_access/physical_access_denied.html', {'message': message})

	# Users may not access an area if a required resource is unavailable.
	# Staff are exempt from this rule.
	unavailable_resources = area.required_resources.filter(available=False)
	if unavailable_resources and not user.is_staff:
		log.details = "The user was blocked from entering this area because a required resource was unavailable."
		log.save()
		return render(request, 'area_access/resource_unavailable.html', {'unavailable_resources': unavailable_resources})

	# Users must have at least one billable project in order to enter an area.
	if user.active_project_count() == 0:
		log.details = "The user has no active projects, preventing them from entering an access controlled area."
		log.save()
		return render(request, 'area_access/no_active_projects.html')

	current_area_access_record = user.area_access_record()
	if current_area_access_record and current_area_access_record.area == door.area:
		# No log entry necessary here because all validation checks passed.
		# The log entry is captured when the subsequent choice is made by the user.
		return render(request, 'area_access/already_logged_in.html', {'area': area, 'project': current_area_access_record.project, 'badge_number': user.badge_number})

	previous_area = None
	if user.active_project_count() == 1:
		log.result = PhysicalAccessType.ALLOW
		log.save()

		# Automatically log the user out of any previous area before logging them in to the new area.
		if user.in_area():
			previous_area_access_record = user.area_access_record()
			previous_area_access_record.end = timezone.now()
			previous_area_access_record.updated = timezone.now()
			previous_area_access_record.save()
			previous_area = previous_area_access_record.area

		record = AreaAccessRecord()
		record.area = door.area
		record.customer = user
		record.user = user
		record.project = user.active_projects()[0]
		record.created = timezone.now()
		record.updated = timezone.now()
		record.save()

		aarp = AreaAccessRecordProject()
		aarp.area_access_record = record
		aarp.project = user.active_projects()[0]
		aarp.customer = user
		aarp.created = timezone.now()
		aarp.updated = timezone.now()
		aarp.save()

		samples = request.POST.get("selected_sample")

		if samples != "" and samples is not None and samples != "null":
			samples = samples.split(",")
			for s in samples:
				#aarp.sample.add(Sample.objects.get(id=int(s)))
				aarp.sample_detail.add(Sample.objects.get(id=int(s)))


		if door_id is not None and door_id != 0:
			unlock_door(door.id)
		return render(request, 'area_access/login_success.html', {'area': area, 'name': user.first_name, 'project': record.project, 'previous_area': previous_area})
	elif user.active_project_count() > 1:
		project_id = request.POST.get('project_id')
		if project_id:
			project = get_object_or_404(Project, id=project_id)
			if project not in user.active_projects():
				log.details = "The user attempted to bill the project named {}, but they are not a member of that project.".format(project.name)
				log.save()
				message = "You are not authorized to bill this project."
				return render(request, 'area_access/physical_access_denied.html', {'message': message})
			log.result = PhysicalAccessType.ALLOW
			log.save()

			# Automatically log the user out of any previous area before logging them in to the new area.
			if user.in_area():
				previous_area_access_record = user.area_access_record()
				previous_area_access_record.end = timezone.now()
				previous_area_access_record.updated = timezone.now()
				previous_area_access_record.save()
				previous_area = previous_area_access_record.area

			record = AreaAccessRecord()
			record.area = area
			record.customer = user
			record.user = user
			record.project = project
			record.created = timezone.now()
			record.updated = timezone.now()
			record.save()

			aarp = AreaAccessRecordProject()
			aarp.area_access_record = record
			aarp.project = project
			aarp.customer = user
			aarp.created = timezone.now()
			aarp.updated = timezone.now()
			aarp.save()

			samples = request.POST.get("selected_sample")

			if samples != "" and samples is not None and samples != "null":
				samples = samples.split(",")
				for s in samples:
					#aarp.sample.add(Sample.objects.get(id=int(s)))
					aarp.sample_detail.add(Sample.objects.get(id=int(s)))


			if door_id is not None and door_id != 0:
				unlock_door(door.id)
			return render(request, 'area_access/login_success.html', {'area': area, 'name': user.first_name, 'project': record.project, 'previous_area': previous_area})
		else:
			# No log entry necessary here because all validation checks passed, and the user must indicate which project
			# the wish to login under. The log entry is captured when the subsequent choice is made by the user.
			return render(request, 'area_access/choose_project.html', {'area': area, 'user': user})


@postpone
def unlock_door(door_id):
	door = Door.objects.get(id=door_id)
	door.interlock.unlock()
	sleep(8)
	door.interlock.lock()


@login_required
#@permission_required('NEMO.change_areaaccessrecord')
@require_POST
def logout_of_area(request, door_id=None, area_id=None):
	try:
		badge_number = int(request.POST.get('badge_number', ''))
		user = User.objects.get(badge_number=badge_number)
	except (User.DoesNotExist, ValueError):
		#return render(request, 'area_access/badge_not_found.html')
		user = request.user
	record = user.area_access_record()
	# Allow the user to log out of any area, even if this is a logout tablet for a different area.
	if record:
		record.end = timezone.now()
		record.updated = timezone.now()
		record.comment = request.POST.get("comment")
		record.save()

		aarp = AreaAccessRecordProject.objects.filter(area_access_record=record)
		ar_count = aarp.count()

		if aarp is not None:
			for a in aarp:
				a.project_percent = round((100/ar_count), 2)
				a.updated = timezone.now()
				a.save()

		#return render(request, 'area_access/logout_success.html', {'area': record.area, 'name': user.first_name})
		return HttpResponseRedirect('/new_area_access_record/' + str(user.id) + '/')
		#return HttpResponse()
	else:
		return render(request, 'area_access/not_logged_in.html')


@login_required
@require_POST
def force_area_logout(request, user_id):
	user = get_object_or_404(User, id=user_id)
	record = user.area_access_record()
	if record is None:
		return HttpResponseBadRequest('That user is not logged into any areas.')
	record.end = timezone.now()
	record.updated = timezone.now()
	record.save()

	if record.related_usage_event is not None:
		# match the percentages for the area access record projects to the usage event project records
		uep = UsageEventProject.objects.filter(usage_event=record.related_usage_event)

		for u in uep:
			aarp = AreaAccessRecordProject.objects.get(area_access_record=record, project=u.project, customer=u.customer)
			aarp.project_percent = u.project_percent
			aarp.updated = timezone.now()
			aarp.save()

	elif record.staff_charge is not None:
		# match the percentages for the area access record projects to the staff charge project records
		scp = StaffChargeProject.objects.filter(staff_charge=record.staff_charge)

		for s in scp:
			aarp = AreaAccessRecordProject.objects.get(area_access_record=record, project=s.project, customer=s.customer)
			aarp.project_percent = s.project_percent
			aarp.updated = timezone.now()
			aarp.save()

	else:
		# check on the number of project records, then assign values based on the count
		aarp = AreaAccessRecordProject.objects.filter(area_access_record=record)
		num_records = aarp.count()
		
		for a in aarp:
			a.project_percent = round((100/num_records),2)
			a.updated = timezone.now()
			a.save()

	return HttpResponse()


@login_required
@permission_required('NEMO.change_areaaccessrecord')
@require_POST
def open_door(request, door_id):
	door = get_object_or_404(Door, id=door_id)
	badge_number = request.POST.get('badge_number', '')
	try:
		badge_number = int(badge_number)
		user = User.objects.get(badge_number=badge_number)
	except (User.DoesNotExist, ValueError):
		return render(request, 'area_access/badge_not_found.html')
	if user.area_access_record() and user.area_access_record().area == door.area:
		log = PhysicalAccessLog(user=user, door=door, time=timezone.now(), result=PhysicalAccessType.ALLOW, details="The user was permitted to enter this area, and already had an active area access record for this area.")
		log.save()
		unlock_door(door.id)
		return render(request, 'area_access/door_is_open.html')
	return render(request, 'area_access/not_logged_in.html', {'area': door.area})


@login_required
@require_http_methods(['GET', 'POST'])
def change_project(request, new_project=None):
	""" For area access, allow the user to stop billing a project and start billing another project. """
	staff_check_record = request.user.area_access_record()
	aarp = AreaAccessRecordProject.objects.filter(area_access_record=staff_check_record)
	if aarp.count() > 1:
		dictionary = {
			'error': "You're charging area access to a customer - you can't change projects via this method"
		}
		return render(request, 'area_access/change_project.html', dictionary)
	else:
		if aarp.count() == 1:
			if not aarp[0].project in request.user.active_projects():
				dictionary = {
					'error': "You're charging area access to a customer - you can't change projects via this method"
				}
				return render(request, 'area_access/change_project.html', dictionary)
			else:
				if aarp[0].customer != request.user:
					dictionary = {
						'error': "You're charging area access to a customer - you can't change projects via this method"
					}
					return render(request, 'area_access/change_project.html', dictionary)


	if request.method == 'GET':
		return render(request, 'area_access/change_project.html')
	old_project = request.user.billing_to_project()
	if old_project is None:
		dictionary = {
			'error': "There was a problem changing the project you're billing for area access. You must already be billing a project in order to change to another project, however you were not logged in to an area."
		}
		return render(request, 'area_access/change_project.html', dictionary)
	# If we're already billing the requested project then there's nothing to do.
	if old_project.id == new_project:
		return redirect(reverse('landing'))
	new_project = get_object_or_404(Project, id=new_project)
	if new_project not in request.user.active_projects():
		dictionary = {
			'error': 'You do not have permission to bill that project.'
		}
		return render(request, 'area_access/change_project.html', dictionary)
	# Stop billing the user's initial project
	record = request.user.area_access_record()
	record.end = timezone.now()
	record.updated = timezone.now()
	record.save()
	area = record.area

	record_projects = AreaAccessRecordProject.objects.filter(area_access_record=record)

	# Start billing the user's new project
	record = AreaAccessRecord()
	record.area = area
	record.customer = request.user
	record.user = request.user
	record.project = new_project
	record.created = timezone.now()
	record.updated = timezone.now()
	record.save()

	for rp in record_projects:
		aarp = AreaAccessRecordProject()
		aarp.area_access_record = record
		aarp.project = new_project
		aarp.customer = rp.customer
		aarp.created = timezone.now()
		aarp.updated = timezone.now()
		aarp.save()


	return redirect(reverse('landing'))


@login_required
@require_http_methods(['GET', 'POST'])
def new_area_access_record(request, customer=None):
	dictionary = {
		'customers': User.objects.filter(is_active=True, projects__active=True).distinct()
	}

	if request.user.core_ids.count() > 1:
		dictionary['multi_core_user'] = True
	else:
		dictionary['multi_core_user'] = False

	if request.method == 'GET':
		try:
			if request.user.is_staff and request.GET.get('customer') is None and customer is None:
				# present a simple search filter to choose a user
				return render(request, 'area_access/new_area_access_record.html', dictionary)
			if customer:
				customer_to_send = User.objects.get(id=customer, is_active=True)
				dictionary['self_login_flag'] = True
			else:
				if request.GET['customer']:
					customer_to_send = User.objects.get(id=request.GET['customer'], is_active=True)
					dictionary['self_login_flag'] = False
				else:
					customer_to_send = request.user
					dictionary['self_login_flag'] = True

			dictionary['customer'] = customer_to_send
			dictionary['areas'] = list(set([access_level.area for access_level in customer_to_send.physical_access_levels.all()]))
			if customer_to_send.active_project_count() == 0:
				dictionary['error_message'] = '{} does not have any active projects to bill area access'.format(customer_to_send)
				return render(request, 'area_access/new_area_access_record.html', dictionary)
			if not dictionary['areas']:
				dictionary['error_message'] = '{} does not have access to any billable laboratory areas'.format(customer_to_send)
				return render(request, 'area_access/new_area_access_record.html', dictionary)


			dates = get_billing_date_range()
			dictionary['start_date'] = dates['start']
			dictionary['end_date'] = dates['end']
			dictionary['users'] = User.objects.filter(is_active=True, projects__active=True).distinct()

			# set a flag and check the user's profile to determine if the extra confirmation should be used
			show_confirm = False
			confirm_setting = UserProfileSetting.objects.get(name="SHOW_CONFIRMATION")

			if UserProfile.objects.filter(user=request.user, setting=confirm_setting).exists():
				setting = UserProfile.objects.get(user=request.user, setting=confirm_setting)
				show_confirm = bool(int(setting.value))

			dictionary['show_confirm'] = show_confirm

			return render(request, 'area_access/new_area_access_record_details.html', dictionary)
		except Exception as inst:
			#raise Exception()
			dictionary['error_message'] = inst
			return render(request, 'area_access/new_area_access_record.html', dictionary)

		return render(request, 'area_access/new_area_access_record.html', dictionary)
	if request.method == 'POST':
		try:
			user = User.objects.get(id=request.POST['customer'], is_active=True)
			self_login_flag = user == request.user
			project = Project.objects.get(id=request.POST['project'])
			area = Area.objects.get(id=request.POST['area'])
		except:
			dictionary['error_message'] = 'Your request contained an invalid identifier.'
			return render(request, 'area_access/new_area_access_record.html', dictionary)
		if user.access_expiration is not None and user.access_expiration < timezone.now().date():
			dictionary['error_message'] = '{} does not have access to the {} because the user\'s physical access expired on {}. You must update the user\'s physical access expiration date before creating a new area access record.'.format(user, area.name.lower(), user.access_expiration.strftime('%B %m, %Y'))
			return render(request, 'area_access/new_area_access_record.html', dictionary)
		if not any([access_level.accessible() for access_level in user.physical_access_levels.filter(area=area)]):
			dictionary['error_message'] = '{} does not have a physical access level that allows access to the {} at this time.'.format(user, area.name.lower())
			return render(request, 'area_access/new_area_access_record.html', dictionary)
		if user.billing_to_project():
			dictionary['error_message'] = '{} is already billing area access to another area. The user must log out of that area before entering another.'.format(user)
			return render(request, 'area_access/new_area_access_record.html', dictionary)
		if project not in user.active_projects():
			dictionary['error_message'] = '{} is not authorized to bill that project.'.format(user)
			return render(request, 'area_access/new_area_access_record.html', dictionary)
		if area.required_resources.filter(available=False).exists():
			dictionary['error_message'] = 'The {} is inaccessible because a required resource is unavailable. You must make all required resources for this area available before creating a new area access record.'.format(area.name.lower())
			return render(request, 'area_access/new_area_access_record.html', dictionary)
		record = AreaAccessRecord()
		record.area = area
		record.customer = user
		record.user = user
		record.project = project
		record.created = timezone.now()
		record.updated = timezone.now()
		record.save()
		aarp = AreaAccessRecordProject()
		aarp.area_access_record = record
		aarp.project = project
		aarp.customer = user
		aarp.created = timezone.now()
		aarp.updated = timezone.now()
		aarp.save()

		samples = request.POST.get("selected_sample")

		if samples != "" and samples is not None and samples != "null":
			samples = samples.split(",")
			for s in samples:
				#aarp.sample.add(Sample.objects.get(id=int(s)))
				aarp.sample_detail.add(Sample.objects.get(id=int(s)))

		dictionary['success'] = '{} is now logged in to the {}.'.format(user, area.name.lower())
		if request.POST['self_login_flag'] == "True":
			return HttpResponseRedirect(reverse('landing'))
		else:
			return render(request, 'area_access/new_area_access_record.html', dictionary)


@login_required
@require_http_methods(['GET', 'POST'])
def self_log_in(request):
	if not able_to_self_log_in_to_area(request.user):
		return redirect(reverse('landing'))
	dictionary = {
		'projects': request.user.active_projects(),
	}
	areas = []
	for access_level in request.user.physical_access_levels.all():
		unavailable_resources = access_level.area.required_resources.filter(available=False)
		if access_level.accessible() and not unavailable_resources:
			areas.append(access_level.area)
	dictionary['areas'] = areas
	if request.method == 'GET':
		return render(request, 'area_access/self_login.html', dictionary)
	if request.method == 'POST':
		try:
			a = Area.objects.get(id=request.POST['area'])
			p = Project.objects.get(id=request.POST['project'])
			
			if a in dictionary['areas'] and p in dictionary['projects']:
				if AreaAccessRecord.objects.filter(customer=request.user, end=None, active_flag=True).count() > 0:
					areas = AreaAccessRecord.objects.filter(customer=request.user, end=None, active_flag=True)
					for a in areas:
						a.end = timezone.now()
						a.save()

				record = AreaAccessRecord.objects.create(area=a, customer=request.user, project=p, created=timezone.now(), updated=timezone.now())
				AreaAccessRecordProject.objects.create(area_access_record=record, customer=request.user, project=p, created=timezone.now(), updated=timezone.now())
		except:
			pass
		return redirect(reverse('landing'))


def able_to_self_log_in_to_area(user):
	# 'Self log in' must be enabled
	if not get_customization('self_log_in') == 'enabled':
		return False
	# Check if the user is active
	if not user.is_active:
		return False
	# Check if the user has a billable project
	if user.active_project_count() < 1:
		return False
	# Check if the user is already in an area. If so, the /change_project/ URL can be used to change their project.
	if user.in_area():
		return False
	# Check if the user has any physical access levels
	if not user.physical_access_levels.all().exists():
		return False
	# Check if the user normally has access to this area at the current time
	accessible_areas = []
	for access_level in user.physical_access_levels.all():
		if access_level.accessible():
			accessible_areas.append(access_level.area)
	if not accessible_areas:
		return False
	# Check that the user's physical access has not expired
	if user.access_expiration is not None and user.access_expiration < date.today():
		return False
	# Staff are exempt from the remaining rule checks
	if user.is_staff:
		return True
	# Users may not access an area if a required resource is unavailable,
	# so return true if there exists at least one area they are able to log in to.
	for area in accessible_areas:
		unavailable_resources = area.required_resources.filter(available=False)
		if not unavailable_resources:
			return True
	# No areas are accessible...
	return False


@login_required
@require_GET
def save_area_access_comment(request):
	id = request.GET.get('area_access_id')
	aar = AreaAccessRecord.objects.get(id=id)
	aar.comment = request.GET.get('area_access_comment')
	aar.save()
	return HttpResponse()


@login_required
@require_POST
def ad_hoc_area_access_record(request):
	aar = AreaAccessRecord()
	aar.area = Area.objects.get(id=request.POST.get("ad_hoc_area"))
	aar.project = Project.objects.get(id=request.POST.get("ad_hoc_project"))
	if request.POST.get("area_user"):
		aar.customer = User.objects.get(id=request.POST.get("area_user"))
		aar.user = User.objects.get(id=request.POST.get("area_user"))
	else:
		aar.customer = User.objects.get(id=request.user.id)
		aar.user = User.objects.get(id=request.user.id)
	start = parse_datetime(request.POST.get("ad_hoc_start"))
	aar.start = start.astimezone(timezone.get_current_timezone())
	end = parse_datetime(request.POST.get("ad_hoc_end"))
	aar.end = end.astimezone(timezone.get_current_timezone())
	aar.ad_hoc_created = True
	aar.created = timezone.now()
	aar.updated = timezone.now()
	if request.POST.get("area_access_comment") is not None:
		aar.comment = request.POST.get("area_access_comment")
	aar.save()

	aarp = AreaAccessRecordProject()
	aarp.area_access_record = aar
	aarp.project = aar.project
	aarp.customer = aar.customer
	aarp.project_percent = 100.0
	aarp.created = timezone.now()
	aarp.updated = timezone.now()
	aarp.save()

	samples = request.POST.get("selected_sample")

	if samples != "" and samples is not None and samples != "null":
		samples = samples.split(",")
		for s in samples:
			aarp.sample_detail.add(Sample.objects.get(id=int(s)))



	return HttpResponseRedirect(reverse('landing'))


@login_required
@require_POST
def end_area_access_charge(request):
	try:
		aar = request.user.area_access_record()
		aar.end = timezone.now()
		aar.updated = timezone.now()
		aar.save()

		use_tool_percents = request.POST.get("use_tool_percents") == 'true'

		if use_tool_percents:
			uep = UsageEventProject.objects.filter(usage_event=aar.related_usage_event)

			for u in uep:
				aarp = AreaAccessRecordProject.objects.get(area_access_record=aar, project=u.project, customer=u.customer)
				aarp.project_percent = u.project_percent
				aarp.save()

			return render(request, 'tool_control/disable_confirmation.html', {'tool': aar.related_usage_event.tool})


	except:
		
		return HttpResponseBadRequest('There was an error attempting to end your area access record.')

	return HttpResponseRedirect(reverse('landing'))
