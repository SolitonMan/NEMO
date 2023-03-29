from re import search

import requests
import string
from datetime import timedelta, datetime
from decimal import Decimal

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.core import mail
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseRedirect
from django.db.models import Q, Max
from django.shortcuts import render, redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_time, parse_date, parse_datetime
from django.utils.html import strip_tags
from django.views.decorators.http import require_GET, require_POST

from NEMO.models import User, StaffCharge, Sample, AreaAccessRecord, Project, Area, StaffChargeProject, AreaAccessRecordProject, LockBilling, UserProfile, UserProfileSetting, UsageEvent, UsageEventProject, StaffChargeNotificationLog


@require_GET
def save_staff_comment(request):
	staff_charge_id = int(request.GET['staff_charge_id'])
	charge = StaffCharge.objects.get(id=staff_charge_id)
	charge.staff_member_comment = request.GET['staff_member_comment']
	charge.updated = timezone.now()
	charge.save()
	return HttpResponse()

@require_GET
def save_sc_customer_comment(request):
	scp_id = int(request.GET['scp_id'])
	scp = StaffChargeProject.objects.get(id=scp_id)
	scp.comment = request.GET['comment']
	scp.updated = timezone.now()
	scp.save()
	return HttpResponse()


@staff_member_required(login_url=None)
@require_GET
def staff_charges(request):
	staff_charge = request.user.get_staff_charge()
	params = {
		"area": None,
		"staff_charge": None,
		"scp": None,
		"areas": None,
	}
	render_path = ''

	charging_staff_time = False
	charging_area_time = False

	if staff_charge:
		charging_staff_time = True
		try:
			area_access_record = AreaAccessRecord.objects.get(staff_charge=staff_charge.id, end=None, active_flag=True)
			params['area'] = area_access_record.area
			params['staff_charge'] = staff_charge
			params['scp'] = StaffChargeProject.objects.filter(staff_charge=staff_charge, active_flag=True)
			charging_area_time = True
			#render_path = 'staff_charges/end_area_charge.html'

			#return render(request, 'staff_charges/end_area_charge.html', {'area': area_access_record.area, 'staff_charge': staff_charge, 'scp': StaffChargeProject.objects.filter(staff_charge=staff_charge, active_flag=True)})
		#except AreaAccessRecord.DoesNotExist:


		except:
			scp = StaffChargeProject.objects.filter(staff_charge=staff_charge, active_flag=True)
			params['scp'] = scp
			params['areas'] = Area.objects.all()
			params['staff_charge'] = staff_charge
			#render_path = 'staff_charges/change_status.html'
			#return render(request, 'staff_charges/change_status.html', {'areas': Area.objects.all(), 'scp': scp, 'staff_charge': staff_charge})
	error = None
	customer = None
	try:
		customer = User.objects.get(id=request.GET['customer'])
	except:
		pass
	if customer:
		if customer.active_project_count() > 0:
			return render(request, 'staff_charges/choose_project.html', {'customer': customer})
		else:
			error = str(customer) + ' does not have any active projects. You cannot bill staff time to this user.'
	users = User.objects.filter(is_active=True).exclude(id=request.user.id)

	params['users'] = users 
	params['error'] = error

	# if the user has any open charges pass the information to the form
	overridden_charges = StaffCharge.objects.filter(staff_member=request.user, charge_end_override=True, override_confirmed=False, active_flag=True)

	if overridden_charges.count() > 0:
		params['override_charges'] = overridden_charges
		oscp = StaffChargeProject.objects.filter(staff_charge__in=overridden_charges, active_flag=True)

		if oscp.count() > 0:
			params['oscp'] = oscp

	# get all staff charges for this user so ad hoc charges can be made with an appropriate reference
	earliest = timezone.now().date() - timedelta(days=30)
	latest = timezone.now().date() + timedelta(days=90)
	my_staff_charges = StaffCharge.objects.filter(staff_member=request.user, start__range=(earliest, latest), active_flag=True)
	if my_staff_charges:
		params['current_user_charges'] = my_staff_charges

	# include start and end dates for ad hoc charge min and max values
	dates = get_billing_date_range()

	params['start_date'] = dates['start']
	params['end_date'] = dates['end']

	if request.user.core_ids.count() > 1:
		params['multi_core_user'] = True
	else:
		params['multi_core_user'] = False

	if request.user.core_ids.filter(name='Engineering Shop Services').exists():
		params['show_no_staff_charge_option'] = True
	else:
		params['show_no_staff_charge_option'] = False

	# temporarily disabling the show no staff charge option
	params['show_no_staff_charge_option'] = False

	if render_path == '':
		render_path = 'staff_charges/new_staff_charge.html'


	# set a flag and check the user's profile to determine if the extra confirmation should be used
	show_confirm = False
	confirm_setting = UserProfileSetting.objects.get(name="SHOW_CONFIRMATION")

	if UserProfile.objects.filter(user=request.user, setting=confirm_setting).exists():
		setting = UserProfile.objects.get(user=request.user, setting=confirm_setting)
		show_confirm = bool(int(setting.value))

	params['show_confirm'] = show_confirm
	params['charging_staff_time'] = charging_staff_time
	params['charging_area_time'] = charging_area_time

	return render(request, render_path, params)


@staff_member_required(login_url=None)
@require_POST
def begin_staff_charge(request):
	if request.user.charging_staff_time():
		return HttpResponseBadRequest('You cannot create a new staff charge when one is already in progress.')

	charge = StaffCharge()

	try:
		charge.staff_member = request.user
		charge.created = timezone.now()
		charge.updated = timezone.now()
		if request.POST.get('core_select', None) != None:
			charge.core_id_override = int(request.POST.get('core_select'))
		charge.save()

		project_charges = {}
		sample_selections = {}

		for key, value in request.POST.items():
			if is_valid_field(key):
				attribute, separator, index = key.partition("__")
				index = int(index)
				if index not in project_charges:
					project_charges[index] = StaffChargeProject()
					project_charges[index].staff_charge = charge
					project_charges[index].created = timezone.now()
					project_charges[index].updated = timezone.now()
				if attribute == "chosen_user":
					if value is not None and value != "":
						project_charges[index].customer = User.objects.get(id=value)
					else:
						charge.delete()
						return HttpResponseBadRequest('Please choose a customer')

				if attribute == "chosen_project":
					if value is not None and value != "" and value != "-1":
						cp = Project.objects.get(id=value)
						if cp.check_date(charge.start):
							project_charges[index].project = Project.objects.get(id=value)	
						else:
							msg = "The selected project " + str(cp.project_number) + " is not valid for use on a transaction with a start date of " + str(charge.start) + " because the start date of the project is " + str(cp.start_date)
							charge.delete()
							return HttpResponseBadRequest(msg)
					else:
						charge.delete()
						return HttpResponseBadRequest('Please choose a project to which to bill your staff charges')

				if attribute == "chosen_sample":
					sample_field = "selected_sample__" + str(index)
					samples = request.POST.get(sample_field)
					sample_selections[index] = samples.split(",")

		for p in project_charges.values():
			p.full_clean(exclude='project_percent')
			p.save()

		# when everything else is saved for the staff charge, save the sample data
		if sample_selections is not None and sample_selections != {}:
			for k in project_charges.keys():
				if k in sample_selections:
					for s in sample_selections[k]:
						project_charges[k].sample.add(Sample.objects.get(id=int(s)))


	except Exception:
		charge.delete()

		return HttpResponseBadRequest('An error occurred while processing the staff charge project selections. None of the charges were committed to the database. Please review the form for errors and omissions then submit the form again.')

	return redirect(reverse('staff_charges'))


def is_valid_field(field):
	return search("^(chosen_user|chosen_project|project_percent|overlap_choice|event_comment|chosen_sample)__[0-9]+$", field) is not None

def month_is_locked(check_date):
	day = int(check_date.day)
	month = int(check_date.month)
	if day > 24:
		month += 1
	year = int(check_date.year)
	return LockBilling.objects.filter(is_locked=True,billing_month=month,billing_year=year).exists()

def month_is_closed(check_date):
	day = int(check_date.day)
	month = int(check_date.month)
	if day > 24:
		month += 1
	year = int(check_date.year)
	return LockBilling.objects.filter(is_closed=True,billing_month=month,billing_year=year).exists()

def get_billing_date_range():
	if LockBilling.objects.filter(is_locked=True).aggregate(Max('billing_year'))['billing_year__max'] is not None:
		max_year = int(LockBilling.objects.filter(is_locked=True).aggregate(Max('billing_year'))['billing_year__max'])
	else:
		max_year = datetime.today().year

	if LockBilling.objects.filter(billing_year=max_year, is_locked=True).aggregate(Max('billing_month'))['billing_month__max'] is not None:
		max_month = int(LockBilling.objects.filter(billing_year=max_year, is_locked=True).aggregate(Max('billing_month'))['billing_month__max'])
	else:
		max_month = datetime.today().month - 2

	if max_month > 12:
		max_month = 1
		max_year += 1

	start = str(max_month) + '/25/' + str(max_year)
	if max_month == 12:
		end = '1/24/' + str(max_year+1)
	else:
		end = str(max_month + 1) + '/24/' + str(max_year)

	dictionary = {
		'start': start,
		'end': end,
	}

	return dictionary


@staff_member_required(login_url=None)
@require_GET
def staff_charge_entry(request):
	entry_number = int(request.GET['entry_number'])
	return render(request, 'staff_charges/staff_charge_entry.html', {'entry_number': entry_number})



@staff_member_required(login_url=None)
@require_GET
def ad_hoc_staff_charge_entry(request):
	entry_number = int(request.GET['entry_number'])
	return render(request, 'staff_charges/ad_hoc_staff_charge_entry.html', {'entry_number': entry_number})



@staff_member_required(login_url=None)
@require_POST
def ad_hoc_staff_charge(request):
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
			msg = 'The start date and end date are required to save an ad hoc staff charge.'
			raise Exception(msg)

		ad_hoc_start = parse_datetime(ad_hoc_start)
		ad_hoc_end = parse_datetime(ad_hoc_end)

		if ad_hoc_start > ad_hoc_end:
			msg = 'The start date must be before the end date.'
			raise Exception(msg)

		# check for validity of dates for closed month
		if month_is_closed(ad_hoc_start) or month_is_closed(ad_hoc_end):
			msg = 'Billing is closed for the chosen month.  Further changes to the billing cannot be made in LEO.  Please contact a financial administrator for help with your billing issue.'
			raise Exception(msg)

		# check for validity of dates for locked month
		if month_is_locked(ad_hoc_start) or month_is_locked(ad_hoc_end):
			if not request.user.is_superuser and not request.user.groups.filter(name="Financial Admin").exists():
				msg = 'Billing is locked for the chosen month.  Please correct your start or end date, or else contact an administrator for help with this.'
				raise Exception(msg)

		if ad_hoc_start is None or ad_hoc_end is None:
			msg = 'The start date and end date are required to save an ad hoc staff charge. The values must be valid datetimes.'
			raise Exception(msg)

		if StaffCharge.objects.filter(staff_member=request.user, start__range=(ad_hoc_start, ad_hoc_end), end__gt=ad_hoc_end, active_flag=True, ad_hoc_replaced=False).exists() or StaffCharge.objects.filter(staff_member=request.user, end__range=(ad_hoc_start, ad_hoc_end), start__lt=ad_hoc_start, active_flag=True, ad_hoc_replaced=False).exists() or StaffCharge.objects.filter(staff_member=request.user, start__lt=ad_hoc_start, end__gt=ad_hoc_end, active_flag=True, ad_hoc_replaced=False).exists() or StaffCharge.objects.filter(staff_member=request.user, start__gt=ad_hoc_start, end__lt=ad_hoc_end, active_flag=True, ad_hoc_replaced=False).exists():

			if StaffCharge.objects.filter(staff_member=request.user, start__range=(ad_hoc_start, ad_hoc_end), end__gt=ad_hoc_end, charge_end_override=True, override_confirmed=False, active_flag=True, ad_hoc_replaced=False).exists() or StaffCharge.objects.filter(staff_member=request.user, end__range=(ad_hoc_start, ad_hoc_end), start__lt=ad_hoc_start, charge_end_override=True, override_confirmed=False, active_flag=True, ad_hoc_replaced=False).exists() or StaffCharge.objects.filter(staff_member=request.user, start__lt=ad_hoc_start, end__gt=ad_hoc_end, charge_end_override=True, override_confirmed=False, active_flag=True, ad_hoc_replaced=False).exists() or StaffCharge.objects.filter(staff_member=request.user, start__gt=ad_hoc_start, end__lt=ad_hoc_end, charge_end_override=True, override_confirmed=False, active_flag=True, ad_hoc_replaced=False).exists():
				msg = 'You have outstanding staff charges that were overridden and are overlapping with the ad hoc charge you have submitted.  Please resolve any relevant outstanding overridden charges before adding an ad hoc charge during that time period.'
				raise Exception(msg)

			if StaffCharge.objects.filter(staff_member=request.user, start__range=(ad_hoc_start, ad_hoc_end), end__gt=ad_hoc_end, active_flag=True, ad_hoc_replaced=False).exists():
				staff_charges_start = StaffCharge.objects.filter(staff_member=request.user, start__range=(ad_hoc_start, ad_hoc_end), end__gt=ad_hoc_end, active_flag=True, ad_hoc_replaced=False)
			else:
				staff_charges_start = None

			if StaffCharge.objects.filter(staff_member=request.user, end__range=(ad_hoc_start, ad_hoc_end), start__lt=ad_hoc_start, active_flag=True, ad_hoc_replaced=False).exists():
				staff_charges_end = StaffCharge.objects.filter(staff_member=request.user, end__range=(ad_hoc_start, ad_hoc_end), start__lt=ad_hoc_start, active_flag=True, ad_hoc_replaced=False)
			else:
				staff_charges_end = None

			if StaffCharge.objects.filter(staff_member=request.user, start__lt=ad_hoc_start, end__gt=ad_hoc_end, active_flag=True, ad_hoc_replaced=False).exists():
				staff_charges_middle = StaffCharge.objects.filter(staff_member=request.user, start__lt=ad_hoc_start, end__gt=ad_hoc_end, active_flag=True, ad_hoc_replaced=False)
			else:
				staff_charges_middle = None

			if StaffCharge.objects.filter(staff_member=request.user, start__gt=ad_hoc_start, end__lt=ad_hoc_end, active_flag=True, ad_hoc_replaced=False).exists():
				staff_charges_over = StaffCharge.objects.filter(staff_member=request.user, start__gt=ad_hoc_start, end__lt=ad_hoc_end, active_flag=True, ad_hoc_replaced=False)
			else:
				staff_charges_over = None

			params = {
				'staff_charges_start': staff_charges_start,
				'staff_charges_end': staff_charges_end,
				'staff_charges_middle': staff_charges_middle,
				'staff_charges_over': staff_charges_over,
				'ad_hoc_start': request.POST.get('ad_hoc_start'),
				'ad_hoc_end': request.POST.get('ad_hoc_end'),
			}


			pc = {}
			project_ids = []
			customer_ids = []
			ad_hoc_entries = []
			sample_ids = []

			for key, value in request.POST.items():
				if is_valid_field(key):
					attribute, separator, index = key.partition("__")
					index = int(index)

					if index not in pc:
						key1 = "chosen_user__" + str(index)
						key2 = "chosen_project__" + str(index)
						key3 = "project_percent__" + str(index)
						cust = request.POST.get(key1)
						if cust is '' or cust is None:
							msg = 'Customer is a required field for an ad hoc charge'
							raise Exception(msg)

						proj = request.POST.get(key2)
						if proj is '' or proj is None:
							msg = 'Project is a required field for an ad hoc charge'
							raise Exception(msg)
						perc = request.POST.get(key3)
						if perc is '' or perc is None:
							msg = 'Percent is a required field for an ad hoc charge'
							raise Exception(msg)
						pc[index] = [cust, proj, perc]
						if cust is not '' and cust is not None:
							ad_hoc_entries.append([User.objects.get(id=cust), proj, perc])

					if attribute == "chosen_user":
						customer_ids.append(value)

					if attribute == "chosen_project":
						project_ids.append(value)

					if attribute == "chosen_sample":
						sample_field = "selected_sample__" + str(index)
						samples = request.POST.get(sample_field)
						proj_tag = "chosen_project__"  + str(index)
						sample_ids.append([request.POST.get(proj_tag), samples.split(",")])

			projects = Project.objects.filter(id__in=project_ids)
			customers = User.objects.filter(id__in=customer_ids)
			params['ad_hoc_projects'] = projects
			params['ad_hoc_customers'] = customers
			params['ad_hoc_samples'] = sample_ids
			params['pc'] = pc
			if len(ad_hoc_entries) > 0:
				error_params['ad_hoc_entries'] = ad_hoc_entries
			if request.POST.get("include_area_access") is not None:
				params['include_area_access'] = request.POST.get("include_area_access")
			else:
				params['include_area_access'] = None

			if request.POST.get("area_id") is not None:
				params['area_id'] = request.POST.get("area_id")
			else:
				params['area_id'] = None

			return render(request, 'staff_charges/ad_hoc_overlap.html', params)

		# dates are legitimate and no overlapping conflicts so save ad hoc charge
		save_charge = True
		if request.POST.get("do_not_save_staff_charge") is not None:
			save_charge = False

		charge = StaffCharge()
		charge.staff_member = request.user
		charge.start = ad_hoc_start
		charge.end = ad_hoc_end
		charge.ad_hoc_created = True
		if request.POST.get("staff_member_comment") is not None:
			charge.staff_member_comment = request.POST.get("staff_member_comment")
		charge.created = timezone.now()
		charge.updated = timezone.now()
		if request.POST.get('core_select', None) != None:
			charge.core_id_override = int(request.POST.get('core_select'))

		if save_charge:	
			charge.save()
		else:
			charge.validated = True
			charge.validated_date = timezone.now()
			charge.no_charge_flag = True
			charge.save()

		prc = 0.0

		project_charges = {}
		ad_hoc_entries = []
		sample_selections = {}

		for key, value in request.POST.items():
			if is_valid_field(key):
				attribute, separator, index = key.partition("__")
				index = int(index)
				if index not in project_charges:
					project_charges[index] = StaffChargeProject()
					project_charges[index].staff_charge = charge
					project_charges[index].created = timezone.now()
					project_charges[index].updated = timezone.now()
				if attribute == "chosen_user":
					if value is not None and value != "":
						project_charges[index].customer = User.objects.get(id=value)
					else:
						charge.delete()
						msg = 'Customer is a required field for an ad hoc charge.'
						raise Exception()

				if attribute == "chosen_project":
					if value is not None and value != "" and value != "-1":
						cp = Project.objects.get(id=value)
						if cp.check_date(charge.start):
							project_charges[index].project = Project.objects.get(id=value)	
						else:
							msg = 'The project ' + str(cp.project_number) + ' cannot be used on a transcation with a start date of ' + str(charge.start) + ' because the project start date is ' + str(cp.start_date)
							charge.delete()
							raise Exception()
					else:
						charge.delete()
						msg = 'Please choose a project to which to bill your staff charges for this ad hoc charge.'
						raise Exception()

				if attribute == "chosen_sample":
					sample_field = "selected_sample__" + str(index)
					samples = request.POST.get(sample_field)
					sample_selections[index] = samples.split(",")

				if attribute == "project_percent":
					if value == '':
						msg = 'You must enter a numerical value for the percent to charge to a project for an ad hoc charge.'
						charge.delete()
						raise Exception()
					else:
						prc = prc + float(value)
						project_charges[index].project_percent = value


		if int(prc) != 100:
			msg = 'Percent values must total to 100.0'
			charge.delete()
			raise Exception()

		for p in project_charges.values():
			p.full_clean()
			if not save_charge:
				p.no_charge_flag = True
			p.save()

		if sample_selections is not None and sample_selections != {}:
			for k in project_charges.keys():
				if k in sample_selections:
					for s in sample_selections[k]:
						project_charges[k].sample.add(Sample.objects.get(id=int(s)))

		params['staff_charges'] = StaffCharge.objects.filter(id=charge.id, active_flag=True)
		params['no_staff_charge_saved'] = save_charge == False

		if request.POST.get("include_area_access") is not None:
			area_id = request.POST.get("area_id")
			aar = AreaAccessRecord()
			aar.area = Area.objects.get(id=area_id)
			aar.staff_charge = charge
			aar.user = request.user
			aar.ad_hoc_created = True
			aar.start = ad_hoc_start
			aar.end = ad_hoc_end
			aar.created = timezone.now()
			aar.updated = timezone.now()
			aar.save()

			params['area'] = aar.area

			for pc in project_charges:
				aarp = AreaAccessRecordProject()
				aarp.area_access_record = aar
				aarp.project = project_charges[pc].project
				aarp.customer = project_charges[pc].customer
				aarp.project_percent = project_charges[pc].project_percent
				aarp.created = timezone.now()
				aarp.updated = timezone.now()
				aarp.save()

				for s in project_charges[pc].sample.all():
					aarp.sample.add(s)


	except Exception as inst:
		# collect form submission values for display
		pc = {}
		ad_hoc_entries = []

		for key, value in request.POST.items():
			if is_valid_field(key):
				attribute, separator, index = key.partition("__")
				index = int(index)

				if index not in pc:
					key1 = "chosen_user__" + str(index)
					key2 = "chosen_project__" + str(index)
					key3 = "project_percent__" + str(index)
					tmpUser = None
					tmpProj = None
					cust = request.POST.get(key1)
					if cust is not '' and cust is not None:
						tmpUser = User.objects.get(id=cust)
					proj = request.POST.get(key2)
					if proj is not '' and proj is not None:
						tmpProj = Project.objects.get(id=proj)
					perc = request.POST.get(key3)
					pc[index] = [cust, proj, perc]
					ad_hoc_entries.append([tmpUser, tmpProj, perc])

		if len(ad_hoc_entries) > 0:
			error_params['ad_hoc_entries'] = ad_hoc_entries

		users = User.objects.filter(is_active=True, projects__active=True).exclude(id=request.user.id).distinct()

		params['users'] = users

		# if the user has any open charges pass the information to the form
		overridden_charges = StaffCharge.objects.filter(staff_member=request.user, charge_end_override=True, override_confirmed=False, active_flag=True)

		if overridden_charges.count() > 0:
			params['override_charges'] = overridden_charges
			scp = StaffChargeProject.objects.filter(staff_charge__in=overridden_charges, active_flag=True)
			if scp.count() > 0:
				params['scp'] = scp

		# get all staff charges for this user so ad hoc charges can be made with an appropriate reference
		my_staff_charges = StaffCharge.objects.filter(staff_member=request.user, active_flag=True)
		if my_staff_charges:
			params['current_user_charges'] = my_staff_charges

		if msg == '':
			params['error'] = inst
		else:
			params['error'] = msg

		for key, value in error_params.items():
			params[key] = value

		# get date range for ad hoc billing mins and maxes
		dates = get_billing_date_range()
		params['start_date'] = dates['start']
		params['end_date'] = dates['end']

		if request.user.core_ids.count() > 1:
			params['multi_core_user'] = True
		else:
			params['multi_core_user'] = False

		return render(request, 'staff_charges/new_staff_charge.html', params)

	except ValueError as inst:
		# collect form submission values for display
		pc = {}
		ad_hoc_entries = []

		for key, value in request.POST.items():
			if is_valid_field(key):
				attribute, separator, index = key.partition("__")
				index = int(index)

				if index not in pc:
					key1 = "chosen_user__" + str(index)
					key2 = "chosen_project__" + str(index)
					key3 = "project_percent__" + str(index)
					tmpUser = None
					tmpProj = None
					cust = request.POST.get(key1)
					if cust is not '' and cust is not None:
						tmpUser = User.objects.get(id=cust)
					proj = request.POST.get(key2)
					if proj is not '' and proj is not None:
						tmpProj = Project.objects.get(id=proj)
					perc = request.POST.get(key3)
					pc[index] = [cust, proj, perc]
					ad_hoc_entries.append([tmpUser, tmpProj, perc])

		if len(ad_hoc_entries) > 0:
			error_params['ad_hoc_entries'] = ad_hoc_entries

		users = User.objects.filter(is_active=True, projects__active=True).exclude(id=request.user.id).distinct()

		params = {'users': users}

		# if the user has any open charges pass the information to the form
		overridden_charges = StaffCharge.objects.filter(staff_member=request.user, charge_end_override=True, override_confirmed=False, active_flag=True)

		if overridden_charges.count() > 0:
			params['override_charges'] = overridden_charges
			scp = StaffChargeProject.objects.filter(staff_charge__in=overridden_charges, active_flag=True)
			if scp.count() > 0:
				params['scp'] = scp

		# get all staff charges for this user so ad hoc charges can be made with an appropriate reference
		my_staff_charges = StaffCharge.objects.filter(staff_member=request.user, active_flag=True)
		if my_staff_charges:
			params['current_user_charges'] = my_staff_charges

		params['error'] = inst

		for key, value in error_params.items():
			params[key] = value

		if request.user.core_ids.count() > 1:
			params['multi_core_user'] = True
		else:
			params['multi_core_user'] = False

		return render(request, 'staff_charges/new_staff_charge.html', params)	

	return render(request, 'staff_charges/ad_hoc_confirmation.html', params)


@staff_member_required(login_url=None)
@require_POST
def ad_hoc_overlap_resolution(request):
	try:
		output = ''
		msg = ''

		for key, value in request.POST.items():
			output += key + ' = ' + value + '<br/>'

		# assess the conflicted staff charge(s)
		conflicted_charges = {}
		ad_hoc_cp = {}
		overlap_ids = []
		sc_changed = []
		include_area_access = request.POST.get("include_area_access")
		area_id = request.POST.get("area_id")
	
		for key, value in request.POST.items():
			if is_valid_field(key):
				attribute, separator, index = key.partition("__")
				index = int(index)
			
				if attribute == "overlap_choice" and index not in conflicted_charges:
					conflicted_charges[index] = [index, value]
					overlap_ids.append(index)

				if attribute == "chosen_user" and index not in ad_hoc_cp:
					ad_hoc_cp[index] = [value, 0, 0, 0]
				if attribute == "chosen_user" and index in ad_hoc_cp:
					ad_hoc_cp[index][0] = value
				if attribute == "chosen_project" and index not in ad_hoc_cp:
					ad_hoc_cp[index] = [0, value, 0, 0]
				if attribute == "chosen_project" and index in ad_hoc_cp:
					ad_hoc_cp[index][1] = value
				if attribute == "project_percent" and index not in ad_hoc_cp:
					ad_hoc_cp[index] = [0, 0, value, 0]
				if attribute == "project_percent" and index in ad_hoc_cp:
					ad_hoc_cp[index][2] = value
				if attribute == "chosen_sample" and index not in ad_hoc_cp:
					s_str = "selected_sample__" + str(index)
					samples = request.POST.get(s_str)
					ad_hoc_cp[index] = [0, 0, 0, samples.split(",")]
				if attribute == "chosen_sample" and index in ad_hoc_cp:
					s_str = "selected_sample__" + str(index)
					samples = request.POST.get(s_str)
					ad_hoc_cp[index][3] = samples.split(",")


		# create initial ad hoc staff charge
		ahc = StaffCharge()
		ahc.start = request.POST.get("ad_hoc_start")
		ahc.end = request.POST.get("ad_hoc_end")
		ahc.ad_hoc_created = True
		ahc.staff_member = request.user
		ahc.created = timezone.now()
		ahc.updated = timezone.now()
		ahc.save()

		if include_area_access is not None and area_id is not None:
			ahaar = AreaAccessRecord()
			ahaar.area = Area.objects.get(id=area_id)
			ahaar.start = request.POST.get("ad_hoc_start")
			ahaar.end = request.POST.get("ad_hoc_end")
			ahaar.ad_hoc_created = True
			ahaar.user = request.user
			ahaar.created = timezone.now()
			ahaar.updated = timezone.now()
			ahaar.staff_charge = ahc
			ahaar.save()
	
		ad_hoc_id = int(ahc.id)
		ad_hoc_charge = StaffCharge.objects.get(id=ad_hoc_id)
	
		for i, a in ad_hoc_cp.items():
			scp = StaffChargeProject()
			scp.staff_charge = ad_hoc_charge
			a0 = a[0]
			a0 = int(a0)
			scp.customer = User.objects.get(id=a0)
			a1 = a[1]
			a1 = int(a1)
			scp.project = Project.objects.get(id=a1)
			a2 = a[2]
			scp.project_percent = Decimal(a2)
			scp.created = timezone.now()
			scp.updated = timezone.now()
			scp.save()

			if a[3] != 0:
				for s in a[3]:
					scp.sample.add(Sample.objects.get(id=int(s)))

			if include_area_access:
				ahaarp = AreaAccessRecordProject()
				ahaarp.area_access_record = ahaar
				ahaarp.customer = User.objects.get(id=a0)
				ahaarp.project = Project.objects.get(id=a1)
				ahaarp.project_percent = Decimal(a2)
				ahaarp.created = timezone.now()
				ahaarp.updated = timezone.now()
				ahaarp.save()

				if a[3] != 0:
					for s in a[3]:
						ahaarp.sample.add(Sample.objects.get(id=int(s)))

		# get the StaffCharges that overlap the ad hoc charge
		overlaps = StaffCharge.objects.filter(id__in=overlap_ids, active_flag=True).order_by("start")
	
		# resolve the difference based on the choice to keep existing or new
		for o in overlaps:
			choice_object = conflicted_charges[o.id]
			choice = int(choice_object[1])
			case = 0

			if ad_hoc_charge.start < o.start and ad_hoc_charge.end < o.end:
				case = 1
	
			if ad_hoc_charge.start > o.start and ad_hoc_charge.end < o.end:
				case = 2

			if ad_hoc_charge.start > o.start and ad_hoc_charge.end > o.end:
				case = 3

			if ad_hoc_charge.start < o.start and ad_hoc_charge.end > o.end:
				case = 4

			if choice == 0:
				if case == 1:
					ad_hoc_charge.end = o.start
					ad_hoc_charge.updated = timezone.now()
					ad_hoc_charge.save()
					sc_changed.append(ad_hoc_charge.id)

				if case == 2:
					ad_hoc_charge.delete()
					msg = 'The ad hoc staff charge you requested was completely overridden by the existing staff charge to which you gave priority.  No new staff charges have been added to the database at this time.'

				if case == 3:
					ad_hoc_charge.start = o.end
					ad_hoc_charge.updated = timezone.now()
					ad_hoc_charge.save()
					sc_changed.append(ad_hoc_charge.id)

				if case == 4:
					# clone ad hoc charge record to new records with (ad_hoc_charge.start, o.start) and (o.end, ad_hoc_end)
					c1 = sc_clone(request, ad_hoc_charge, ad_hoc_charge.start, o.start)
					c2 = sc_clone(request, ad_hoc_charge, o.end, ad_hoc_charge.end)

					replaced = '|' + str(ad_hoc_charge.id) + '|'
					if StaffCharge.objects.filter(ad_hoc_replaced=True, ad_hoc_related__contains=replaced, start__range=(ad_hoc_charge.start, ad_hoc_charge.end), active_flag=True).count() > 0:
						# update necessary records to new replaced ids - should be c1 since the processing is happening from earliest to latest
						replacements = StaffCharge.objects.filter(ad_hoc_replaced=True, ad_hoc_related__contains=replaced, start__range=(ad_hoc_charge.start, ad_hoc_charge.end), active_flag=True)
						for r in replacements:
							to_replace = r.ad_hoc_related
							new_replace = '|' + str(c1.id) + '|'
							to_replace.replace(replaced, new_replace)
							r.ad_hoc_related = to_replace
							r.updated = timezone.now()
							r.save()

					ad_hoc_charge.delete()
					ad_hoc_charge = c2
					sc_changed.append(c1.id)
				

			else:
				if case == 1:
					c1 = sc_clone(request, o, ad_hoc_charge.end, o.end)
					o.ad_hoc_replaced = True
					o.ad_hoc_related = '|' + str(c1.id) + '|'
					o.updated = timezone.now()
					o.save()
					sc_changed.append(c1.id)

				if case == 2:
					c1 = sc_clone(request, o, o.start, ad_hoc_charge.start)
					c2 = sc_clone(request, o, ad_hoc_charge.end, o.end)
					o.ad_hoc_replaced = True
					o.ad_hoc_related = '|' + str(c1.id) + '|' + str(c2.id) + '|'
					o.updated = timezone.now()
					o.save()
					sc_changed.append(c1.id)
					sc_changed.append(c2.id)
	
				if case == 3:
					c1 = sc_clone(request, o, o.start, ad_hoc_charge.start)
					o.ad_hoc_replaced = True
					o.ad_hoc_related = '|' + str(c1.id) + '|'
					o.updated = timezone.now()
					o.save()
					sc_changed.append(c1.id)
	
				if case == 4:
					o.ad_hoc_replaced = True
					o.ad_hoc_related = '|' + str(ad_hoc_charge.id) + '|'
					o.updated = timezone.now()
					o.save()
	
				if AreaAccessRecord.objects.filter(staff_charge=o).exists():
					o_aar = AreaAccessRecord.objects.filter(staff_charge=o)
					for a in o_aar:
						a.active_flag = False
						a.save()
	
		sc_changed.append(ad_hoc_charge.id)
	
		sc_output = StaffCharge.objects.filter(id__in=sc_changed, active_flag=True)
	
		params = {
			'output': None,
			'staff_charges': sc_output,
			'conflicted_charges': None,
			'ad_hoc_cp': None,
			'overlap_ids': None,
			'message': msg,
		}

	except Exception as inst:
		if msg == '':
			return HttpResponseBadRequest(inst)
		else:
			return HttpResponseBadRequest(msg)

	except ValueError as inst:
		return HttpResponseBadRequest(inst)

	return render(request, 'staff_charges/ad_hoc_confirmation.html', params)



def sc_clone(request, charge_to_clone, new_charge_start, new_charge_end):
	new_charge = StaffCharge()
	new_charge.staff_member = request.user
	new_charge.start = new_charge_start
	new_charge.end = new_charge_end
	new_charge.ad_hoc_created = True
	new_charge.created = timezone.now()
	new_charge.updated = timezone.now()
	new_charge.save()

	new_charge_id = int(new_charge.id)
	nc = StaffCharge.objects.get(id=new_charge_id)

	scp = StaffChargeProject.objects.filter(staff_charge=charge_to_clone, active_flag=True)

	if scp.count() > 0:
		for s in scp:
			new_scp = StaffChargeProject()
			new_scp.staff_charge = nc
			new_scp.project = s.project
			new_scp.customer = s.customer
			new_scp.project_percent = s.project_percent
			new_scp.created = timezone.now()
			new_scp.updated = timezone.now()
			new_scp.save()

	if AreaAccessRecord.objects.filter(staff_charge=charge_to_clone).exists():
		aar_to_clone = AreaAccessRecord.objects.filter(staff_charge=charge_to_clone)

		for a in aar_to_clone:
			new_aar = AreaAccessRecord()
			new_aar.area = a.area
			new_aar.start = nc.start
			new_aar.end = nc.end
			new_aar.ad_hoc_created = True
			new_aar.staff_charge = nc
			new_aar.user = nc.staff_member
			new_aar.customer = nc.customer
			new_aar.created = timezone.now()
			new_aar.updated = timezone.now()
			new_aar.save()

			for rp in AreaAccessRecordProject.objects.filter(area_access_record=a):
				new_aarp = AreaAccessRecordProject()
				new_aarp.area_access_record = new_aar
				new_aarp.project = rp.project
				new_aarp.customer = rp.customer
				new_aarp.project_percent = rp.project_percent
				new_aarp.created = new_aar.created
				new_aarp.updated = new_aar.updated
				new_aarp.save()

	return nc



@staff_member_required(login_url=None)
@require_POST
def end_staff_charge(request, modal_flag):
	if not request.user.charging_staff_time():
		return HttpResponseBadRequest('You do not have a staff charge in progress, so you cannot end it.')
	charge = request.user.get_staff_charge()

	# add any comments the staff member made
	if request.POST.get("staff_member_comment") is not None:
		charge.staff_member_comment = request.POST.get("staff_member_comment")
		charge.save()

	try:
		# close out the project entries for this run
		scp = StaffChargeProject.objects.filter(staff_charge=charge, active_flag=True)

		if scp.count() == 1:
			# set project_percent to 100
			scp = scp[0]
			scp.project_percent = 100.0
			scp.updated = timezone.now()
			scp.save()
			charge.end = timezone.now()
			charge.updated = timezone.now()
			charge.save()

			if AreaAccessRecord.objects.filter(staff_charge=charge, active_flag=True).exists():
				aars = AreaAccessRecord.objects.filter(staff_charge=charge)		# multiple areas may be accessed during on staff charge
				for aar in aars:
					if aar.end is None:
						aar.end = timezone.now()
						aar.updated = timezone.now()
						aar.save()

					aarp = AreaAccessRecordProject.objects.filter(area_access_record=aar, active_flag=True)

					if aarp is not None:
						for a in aarp:
							a.project_percent = 100.0
							a.updated = timezone.now()
							a.save()


			return update_related_charges(request, charge, StaffCharge.objects.get(related_override_charge=charge))

		else:

			use_tool_percents = request.POST.get("use_tool_percents") == 'true'

			if use_tool_percents:
				uep = UsageEventProject.objects.filter(usage_event=charge.related_usage_event)

				for u in uep:
					staff_charge_project = StaffChargeProject.objects.get(staff_charge=charge, project=u.project, customer=u.customer)
					staff_charge_project.project_percent = u.project_percent
					staff_charge_project.save()

				charge.end = timezone.now()
				charge.updated = timezone.now()
				charge.save()
				
				if request.user.area_access_record() is None:
					return render(request, 'tool_control/disable_confirmation.html', {'tool': charge.related_usage_event.tool})
				else:
					return render(request, 'area_access/reminder.html', {'tool':charge.related_usage_event.tool, 'area_access_record': request.user.area_access_record()})
			else:
				# gather records and send to form for editing
				params = {
					'charge': charge,
					'scp': scp,
					'staff_charge_id': charge.id,
					'total_minutes': (timezone.now() - charge.start).total_seconds()//60,
					'staff_member_comment': request.POST.get("staff_member_comment")
				}
				if int(modal_flag) == 0:
					return render(request, 'staff_charges/multiple_projects_finish.html', params)
				else:
					tool_id = request.POST.get("tool_id")
					params["tool_id"] = tool_id
					return render(request, 'staff_charges/modal_multiple_projects_finish.html', params)


	except ObjectDoesNotExist:
		return update_related_charges(request, charge, None)

	return redirect(reverse('staff_charges'))


@staff_member_required(login_url=None)
@require_POST
def staff_charge_projects_save(request, modal_flag):
	msg = ''

	try:
		prc = 0.0
		staff_charge_id = int(request.POST.get("staff_charge_id"))
		charge = StaffCharge.objects.get(id=staff_charge_id)

		for key, value in request.POST.items():
			if is_valid_field(key):
				attribute, separator, scpid = key.partition("__")
				scpid = int(scpid)
				if not charge.id:
					s = StaffChargeProject.objects.filter(id=scpid, active_flag=True)
					charge = s[0].staff_charge

				if attribute == "project_percent":
					if value == '':
						msg = 'You must enter a numerical value for the percent to charge to a project'
						if not charge.charge_end_override:
							charge.end=null
							charge.updated = timezone.now()
							charge.save()
						raise Exception()
					else:
						prc = prc + float(value)

		if int(prc) != 100:
			msg = 'Percent values must total to 100.0'
			if not charge.charge_end_override:
				charge.end=null
				charge.updated = timezone.now()
				charge.save()
			raise Exception()

		for key, value in request.POST.items():
			if is_valid_field(key):
				attribute, separator, scpid = key.partition("__")
				scpid = int(scpid)

				if attribute == "event_comment":
					scp = StaffChargeProject.objects.get(id=scpid)
					scp.comment = value
					scp.updated = timezone.now()
					scp.save()

				if attribute == "project_percent":
					scp = StaffChargeProject.objects.get(id=scpid)
					scp.project_percent = value
					scp.updated = timezone.now()
					scp.save()

		if not charge.charge_end_override:
			charge.end = timezone.now()
		if charge.charge_end_override:
			charge.override_confirmed = True
		if request.POST.get("staff_member_comment") is not None:
			charge.staff_member_comment = request.POST.get("staff_member_comment")
		charge.updated = timezone.now()
		charge.save()

		# assign percentages to related staff charge project entries
		# create placeholder charge variable so processing with existing charge can continue further on
		check_charge = charge

		while StaffCharge.objects.filter(related_override_charge=check_charge, active_flag=True).count() > 0:
			old_charge = StaffCharge.objects.get(related_override_charge=check_charge, active_flag=True)
			old_scp = StaffChargeProject.objects.filter(staff_charge=old_charge, active_flag=True)

			for s in old_scp:
				new_scp = StaffChargeProject.objects.get(staff_charge=check_charge, project=s.project, customer = s.customer, active_flag=True)
				s.project_percent=new_scp.project_percent
				s.updated = timezone.now()
				s.save()

			check_charge = old_charge

		# check for area access records related to this staff charge and assign percentages
		if AreaAccessRecord.objects.filter(staff_charge=charge, active_flag=True).exists():
			aar = AreaAccessRecord.objects.filter(staff_charge=charge, active_flag=True)
			for area_access in aar:
				if area_access.end is None:
					area_access.end = charge.end
					area_access.save()

				aarp = AreaAccessRecordProject.objects.filter(area_access_record=area_access, active_flag=True)

				for a in aarp:
					scp = StaffChargeProject.objects.get(staff_charge=charge, project=a.project, customer=a.customer, active_flag=True)
					if scp:
						a.project_percent = scp.project_percent
						a.updated = timezone.now()
						a.save()

	except ObjectDoesNotExist:
		return HttpResponseBadRequest("No entry found related to StaffCharge with id {0}".format(str(charge.id)))

	except Exception as inst:
		if msg == '':
			return HttpResponseBadRequest(inst)
		else:
			return HttpResponseBadRequest(msg)

	if int(modal_flag) == 0:
		return redirect(reverse('staff_charges'))
	else:
		tool_id = request.POST.get("tool_id")
		str_url = "/tool_control/" + tool_id
		return redirect(str_url)


@staff_member_required(login_url=None)
def update_related_charges(request, new_charge=None, old_charge=None):

	if old_charge is None:
		referer = request.META.get('HTTP_REFERER')
		if referer.find("tool") != -1:
			tool = None
			return render(request, 'tool_control/disable_confirmation.html', {'tool': tool})
		return redirect(reverse('staff_charges'))

	# find any outstanding StaffChargeProject entries that need to be updated for a related charge being ended
	try:
		old_charge.override_confirmed = True
		old_charge.updated = timezone.now()
		old_charge.save()

		old_scp = StaffChargeProject.objects.filter(staff_charge=old_charge, active_flag=True)
		
		for s in old_scp:
			new_scp = StaffChargeProject.objects.get(staff_charge=new_charge, project=s.project, customer = s.customer)
			s.project_percent=new_scp.project_percent
			s.updated = timezone.now()
			s.save()

		if StaffCharge.objects.filter(related_override_charge=old_charge, active_flag=True).exists():
			related_charge = StaffCharge.objects.get(related_override_charge=old_charge, active_flag=True)
			return update_related_charges(request, old_charge, related_charge)

		else:
			return update_related_charges(request, old_charge, None)

	except Exception as inst:
		return HttpResponseBadRequest(inst)



@staff_member_required(login_url=None)
def continue_staff_charge(request, staff_charge_id):
	if request.user.charging_staff_time():
		return HttpResponseBadRequest('Please end your current staff charge before continuing an overridden charge.')

	staff_charge = StaffCharge.objects.get(id=staff_charge_id)

	if staff_charge is None:
		return HttpResponseBadRequest('No staff charge was found with the selected cristeria.  Please review your choice and if this problem persists contact a system administrator.')

	try:
		# create a new staff charge and associate with chosen one
		new_staff_charge = StaffCharge()
		new_staff_charge.staff_member = staff_charge.staff_member
		new_staff_charge.start = timezone.now()
		new_staff_charge.charge_end_override = False
		new_staff_charge.override_confirmed = False
		new_staff_charge.created = timezone.now()
		new_staff_charge.updated = timezone.now()
		new_staff_charge.save()

		staff_charge.related_override_charge = new_staff_charge
		staff_charge.override_confirmed = True
		staff_charge.updated = timezone.now()
		staff_charge.save()

		# copy the StaffChargeProject records
		scp = StaffChargeProject.objects.filter(staff_charge=staff_charge, active_flag=True)
		
		if scp.count() > 0:
			for s in scp:
				new_scp = StaffChargeProject()
				new_scp.staff_charge = new_staff_charge
				new_scp.project = s.project
				new_scp.customer = s.customer
				new_scp.created = timezone.now()
				new_scp.updated = timezone.now()
				new_scp.save()

	except Exception as inst:
		return HttpResponseBadRequest(inst)

	return redirect(reverse('staff_charges'))


@staff_member_required(login_url=None)
@require_POST
def begin_staff_area_charge(request):
	charge = request.user.get_staff_charge()
	if not charge:
		return HttpResponseBadRequest('You do not have a staff charge in progress, so you cannot begin an area access charge.')
	if AreaAccessRecord.objects.filter(staff_charge=charge, end=None, active_flag=True).count() > 0:
		return HttpResponseBadRequest('You cannot create an area access charge when one is already in progress.')
	try:
		area = Area.objects.get(id=request.POST['area'])
	except:
		return HttpResponseBadRequest('Invalid area')
	area_access = AreaAccessRecord()
	area_access.area = area
	area_access.user = request.user
	area_access.staff_charge = charge
	area_access.created = timezone.now()
	area_access.updated = timezone.now()
	if charge.related_usage_event is not None:
		area_access.related_usage_event = charge.related_usage_event
	area_access.save()

	scp = StaffChargeProject.objects.filter(staff_charge=charge, active_flag=True)

	for s in scp:
		aarp = AreaAccessRecordProject()
		aarp.area_access_record = area_access
		aarp.project = s.project
		aarp.customer = s.customer
		aarp.created = timezone.now()
		aarp.updated = timezone.now()
		aarp.save()

		for smp in s.sample.all():
			aarp.sample.add(smp)

	return redirect(reverse('staff_charges'))


@staff_member_required(login_url=None)
@require_POST
def end_staff_area_charge(request):
	charge = request.user.get_staff_charge()
	if not charge:
		return HttpResponseBadRequest('You do not have a staff charge in progress, so you cannot end area access.')
	area_access = AreaAccessRecord.objects.get(staff_charge=charge, end=None)
	area_access.end = timezone.now()
	area_access.updated = timezone.now()
	area_access.save()
	return redirect(reverse('staff_charges'))

def email_staff_charge_reminders():
	charges = StaffCharge.objects.filter(active_flag=True, end=None)

	#mail.send_mail("Staff Charge Check Starting", "The staff charge count is " + str(charges.count()), 'dms117@psu.edu', ['dms117@psu.edu'], html_message="The staff charge count is " + str(charges.count()))

	if settings.NOTIFICATION_STAFF_CHARGE_EXCESSIVE_INTERVAL is not None:
		last_sent_interval = int(settings.NOTIFICATION_STAFF_CHARGE_EXCESSIVE_INTERVAL)
	else:
		last_sent_interval = 119

	if settings.NOTIFICATION_STAFF_CHARGE_EXCESSIVE_DEFAULT_BLOCK is not None:
		use_block_limit = int(settings.NOTIFICATION_STAFF_CHARGE_EXCESSIVE_DEFAULT_BLOCK)
	else:
		use_block_limit = 120

	for c in charges:
		b_send_message = False

		#mail.send_mail("Staff Charge Found", strip_tags(str(c)), 'dms117@psu.edu', ['dms117@psu.edu'], html_message=str(c))

		if (timezone.now() - c.start) >= timedelta(minutes=use_block_limit):

			#mail.send_mail("Long Running Staff Charge Found", strip_tags(str(c)), 'dms117@psu.edu', ['dms117@psu.edu'], html_message=str(c))

			if StaffChargeNotificationLog.objects.filter(staff_charge=c).exists():
				scnl = StaffChargeNotificationLog.objects.filter(staff_charge=c).order_by('-sent')
				last_sent = scnl[0].sent
				if (timezone.now() - last_sent) >= timedelta(minutes=last_sent_interval):
					b_send_message = True
			else:
				b_send_message = True

			if b_send_message:
				recipient = c.staff_member
				scp = StaffChargeProject.objects.filter(staff_charge=c)

				if scp.count() > 0:
					customer = scp[0].customer
				else:
					if c.customer is not None:
						customer = c.customer
					else:
						customer = ""

				subject = "Staff charge active since " + str(c.start) 
				if customer is not None and customer != "":
					subject += " for " + str(customer)
	
				message = "<p>Hello " + str(recipient.first_name) + " " + str(recipient.last_name) + ",</p>"
				message += "<p>LEO has detected that you have been charging staff time since " + str(c.start) + ".  If this is intended please ignore this message.  Otherwise, please end the charge at your convenience.   If you have any questions please contact LEOHelp@psu.edu.</p>"
				message += "<p>Thank you,<br>The LEO Team</p>"
	
				mail.send_mail(subject, strip_tags(message), 'LEOHelp@psu.edu', [recipient.email], html_message=message)
	
				s1 = StaffChargeNotificationLog.objects.create(staff_charge=c, message=message, sent=timezone.now())
