from re import search

import requests

from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from NEMO.models import User, StaffCharge, AreaAccessRecord, Project, Area, StaffChargeProject, AreaAccessRecordProject


@staff_member_required(login_url=None)
@require_GET
def staff_charges(request):
	staff_charge = request.user.get_staff_charge()
	if staff_charge:
		try:
			area_access_record = AreaAccessRecord.objects.get(staff_charge=staff_charge.id, end=None)
			return render(request, 'staff_charges/end_area_charge.html', {'area': area_access_record.area})
		except AreaAccessRecord.DoesNotExist:
			return render(request, 'staff_charges/change_status.html', {'areas': Area.objects.all()})
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

	# if the user has any open charges pass the information to the form
	overridden_charges = StaffCharge.objects.filter(staff_member=request.user, charge_end_override=True, override_confirmed=False)

	if overridden_charges.count() > 0:
		scp = StaffChargeProject.objects.filter(staff_charge__in=overridden_charges)

	params = {'users': users, 'error': error}

	if overridden_charges.count() > 0:
		params['override_charges'] = overridden_charges
		if scp.count() > 0:
			params['scp'] = scp

	return render(request, 'staff_charges/new_staff_charge.html', params)


@staff_member_required(login_url=None)
@require_POST
def begin_staff_charge(request):
	if request.user.charging_staff_time():
		return HttpResponseBadRequest('You cannot create a new staff charge when one is already in progress.')

	charge = StaffCharge()

	try:
		#charge = StaffCharge()
		#charge.customer = User.objects.get(id=request.POST['customer'])
		#charge.project = Project.objects.get(id=request.POST['project'])
		charge.staff_member = request.user
		charge.save()

		project_charges = {}

		for key, value in request.POST.items():
			if is_valid_field(key):
				attribute, separator, index = key.partition("__")
				index = int(index)
				if index not in project_charges:
					project_charges[index] = StaffChargeProject()
					project_charges[index].staff_charge = charge
				if attribute == "chosen_user":
					if value is not None and value != "":
						project_charges[index].customer = User.objects.get(id=value)
					else:
						charge.delete()
						return HttpResponseBadRequest('Please choose a customer')

				if attribute == "chosen_project":
					if value is not None and value != "" and value != "-1":
						project_charges[index].project = Project.objects.get(id=value)	
					else:
						charge.delete()
						return HttpResponseBadRequest('Please choose a project to which to bill your staff charges')

		for p in project_charges.values():
			p.full_clean(exclude='project_percent')
			p.save()


	except Exception:
		charge.delete()

		return HttpResponseBadRequest('An error occurred while processing the staff charge project selections. None of the charges were committed to the database. Please review the form for errors and omissions then submit the form again.')

	return redirect(reverse('staff_charges'))


def is_valid_field(field):
	return search("^(chosen_user|chosen_project|project_percent)__[0-9]+$", field) is not None


@staff_member_required(login_url=None)
@require_GET
def staff_charge_entry(request):
	entry_number = int(request.GET['entry_number'])
	return render(request, 'staff_charges/staff_charge_entry.html', {'entry_number': entry_number})

@staff_member_required(login_url=None)
@require_POST
def end_staff_charge(request):
	if not request.user.charging_staff_time():
		return HttpResponseBadRequest('You do not have a staff charge in progress, so you cannot end it.')
	charge = request.user.get_staff_charge()

	try:
		# close out the project entries for this run
		scp = StaffChargeProject.objects.filter(staff_charge=charge)

		if scp.count() == 1:
			# set project_percent to 100
			scp.update(project_percent=100.0)
			charge.end = timezone.now()
			charge.save()

			return update_related_charges(request, charge, StaffCharge.objects.get(related_override_charge=charge))

		else:
			# gather records and send to form for editing
			params = {
				'charge': charge,
				'scp': scp,
				'staff_charge_id': charge.id,
			}
			return render(request, 'staff_charges/multiple_projects_finish.html', params)

		#area_access = AreaAccessRecord.objects.get(staff_charge=charge, end=None)
		#area_access.end = timezone.now()
		#area_access.save()

		# close out any area access record project entries

	#except AreaAccessRecord.DoesNotExist:
	#	pass

	except ObjectDoesNotExist:
		return update_related_charges(request, charge, None)

	return redirect(reverse('staff_charges'))


@staff_member_required(login_url=None)
@require_POST
def staff_charge_projects_save(request):
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
					s = StaffChargeProject.objects.filter(id=scpid)
					charge = s[0].staff_charge

				if attribute == "project_percent":
					if value == '':
						msg = 'You must enter a numerical value for the percent to charge to a project'
						charge.end=null
						charge.save()
						raise Exception()
					else:
						prc = prc + float(value)

		if int(prc) != 100:
			msg = 'Percent values must total to 100.0'
			charge.end=null
			charge.save()
			raise Exception()

		for key, value in request.POST.items():
                        if is_valid_field(key):
                                attribute, separator, scpid = key.partition("__")
                                scpid = int(scpid)
                                if attribute == "project_percent":
                                        StaffChargeProject.objects.filter(id=scpid).update(project_percent=value)		
					
		charge.end = timezone.now()
		if charge.charge_end_override:
			charge.override_confirmed = True
		charge.save()

		# assign percentages to related staff charge project entries

		while StaffCharge.objects.filter(related_override_charge=charge).count() > 0:
			old_charge = StaffCharge.objects.get(related_override_charge=charge)
			old_scp = StaffChargeProject.objects.filter(staff_charge=old_charge)

			for s in old_scp:
				new_scp = StaffChargeProject.objects.get(staff_charge=charge, project=s.project, customer = s.customer)
				s.project_percent=new_scp.project_percent
				s.save()

			charge = old_charge

	except ObjectDoesNotExist:
		return HttpResponseBadRequest("No entry found related to StaffCharge with id {0}".format(str(charge.id)))

	except Exception as inst:
		if msg == '':
			return HttpResponseBadRequest(inst)
		else:
			return HttpResponseBadRequest(msg)

	return redirect(reverse('staff_charges'))


@staff_member_required(login_url=None)
def update_related_charges(request, new_charge=None, old_charge=None):

	if old_charge is None:
                return redirect(reverse('staff_charges'))

	#return HttpResponseBadRequest('update_related_charges for'+str(old_charge.id))

	# find any outstanding StaffChargeProject entries that need to be updated for a related charge being ended
	try:
		old_charge.override_confirmed = True
		old_charge.save()

		old_scp = StaffChargeProject.objects.filter(staff_charge=old_charge)
		
		for s in old_scp:
			new_scp = StaffChargeProject.objects.get(staff_charge=new_charge, project=s.project, customer = s.customer)
			s.project_percent=new_scp.project_percent
			s.save()

		if StaffCharge.objects.filter(related_override_charge=old_charge).exists():
			related_charge = StaffCharge.objects.get(related_override_charge=old_charge)
			return update_related_charges(request, old_charge, related_charge)

		else:
			return update_related_charges(request, old_charge, None)

	except Exception as inst:
		return HttpResponseBadRequest(inst)



@staff_member_required(login_url=None)
def continue_staff_charge(request, staff_charge_id):
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
		new_staff_charge.save()

		staff_charge.related_override_charge = new_staff_charge
		staff_charge.override_confirmed = True
		staff_charge.save()

		# copy the StaffChargeProject records
		scp = StaffChargeProject.objects.filter(staff_charge=staff_charge)
		
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
	if AreaAccessRecord.objects.filter(staff_charge=charge, end=None).count() > 0:
		return HttpResponseBadRequest('You cannot create an area access charge when one is already in progress.')
	try:
		area = Area.objects.get(id=request.POST['area'])
	except:
		return HttpResponseBadRequest('Invalid area')
	area_access = AreaAccessRecord()
	area_access.area = area
	area_access.staff_charge = charge
	area_access.customer = charge.customer
	area_access.project = charge.project
	area_access.save()
	return redirect(reverse('staff_charges'))


@staff_member_required(login_url=None)
@require_POST
def end_staff_area_charge(request):
	charge = request.user.get_staff_charge()
	if not charge:
		return HttpResponseBadRequest('You do not have a staff charge in progress, so you cannot end area access.')
	area_access = AreaAccessRecord.objects.get(staff_charge=charge, end=None)
	area_access.end = timezone.now()
	area_access.save()
	return redirect(reverse('staff_charges'))
