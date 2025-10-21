from datetime import timedelta

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from NEMO.models import Tool, Area, Requirement, ToolRequirement, AreaRequirement, UserRequirementProgress, ServiceType

@staff_member_required(login_url=None)
def add_requirement(request):
	if request.method == "POST":
		name = request.POST.get("name")
		description = request.POST.get("description")
		resource_link = request.POST.get("resource_link")
		retrain_interval_days = request.POST.get("retrain_interval_days") or 365
		if name:
			Requirement.objects.create(
				name=name,
				description=description,
				resource_link=resource_link,
				retrain_interval_days=retrain_interval_days
			)
			return redirect('manage_requirements')
	requirements = Requirement.objects.all()
	return render(request, "requirements/add_requirement.html", {"requirements": requirements})

@login_required
def edit_requirement(request, requirement_id):
	requirement = get_object_or_404(Requirement, id=requirement_id)
	if request.method == "POST":
		requirement.name = request.POST.get("name")
		requirement.description = request.POST.get("description")
		requirement.resource_link = request.POST.get("resource_link")
		requirement.retrain_interval_days = request.POST.get("retrain_interval_days")
		requirement.save()
		return redirect("add_requirement")
	return render(request, "requirements/edit_requirement.html", {"requirement": requirement})

@staff_member_required(login_url=None)
def manage_requirements(request):
	if request.method == "POST":
		obj_type = request.POST.get("obj_type")
		obj_id = request.POST.get("obj_id")
		assigned_ids = request.POST.getlist("assigned_requirements")
		if obj_type == "tool":
			tool = get_object_or_404(Tool, id=obj_id)
			ToolRequirement.objects.filter(tool=tool).exclude(requirement_id__in=assigned_ids).delete()
			for req_id in assigned_ids:
				ToolRequirement.objects.get_or_create(tool=tool, requirement_id=req_id)
		elif obj_type == "area":
			area = get_object_or_404(Area, id=obj_id)
			AreaRequirement.objects.filter(area=area).exclude(requirement_id__in=assigned_ids).delete()
			for req_id in assigned_ids:
				AreaRequirement.objects.get_or_create(area=area, requirement_id=req_id)
		return redirect('manage_requirements')

	tools = Tool.objects.all()
	areas = Area.objects.all()
	requirements = Requirement.objects.all()
	return render(request, 'requirements/manage_requirements.html', {
		'tools': tools,
		'areas': areas,
		'requirements': requirements,
	})

def mark_requirement_completed(user, requirement):
	now = timezone.now()
	retrain_interval = timedelta(days=365)  # or fetch from requirement config
	progress, created = UserRequirementProgress.objects.get_or_create(user=user, requirement=requirement)
	progress.status = 'completed'
	progress.completed_on = now
	progress.expires_on = now + retrain_interval
	progress.save()

def has_valid_requirement(user, requirement):
	try:
		progress = UserRequirementProgress.objects.get(user=user, requirement=requirement)
		return progress.status == 'completed' and (not progress.expires_on or progress.expires_on > timezone.now())
	except UserRequirementProgress.DoesNotExist:
		return False

def send_retraining_notifications():
	soon = timezone.now() + timedelta(days=30)
	expiring = UserRequirementProgress.objects.filter(
		expires_on__lte=soon,
		expires_on__gt=timezone.now(),
		status='completed'
	)
	for progress in expiring:
		send_mail(
			subject=f"Retraining required for {progress.requirement.name}",
			message=f"Your qualification for {progress.requirement.name} expires on {progress.expires_on.date()}. Please retrain.",
			from_email="noreply@yourdomain.com",
			recipient_list=[progress.user.email]
		)

@login_required
@staff_member_required(login_url=None)
def manage_service_type_requirements(request):
	"""
	GET: render page with service types and list of all requirements.
	POST: save assigned requirements for the selected ServiceType.
	"""
	if request.method == "POST":
		st_id = request.POST.get("service_type_id")
		if not st_id:
			messages.error(request, "No ServiceType selected.")
			return redirect('manage_service_type_requirements')

		service_type = get_object_or_404(ServiceType, id=st_id)
		assigned_ids = request.POST.getlist('assigned_requirements')  # list of ids (strings)
		# Replace current assignments with posted list
		service_type.requirements.set(assigned_ids)
		service_type.save()
		messages.success(request, f"Requirements updated for service type: {service_type.name}")
		return redirect('manage_service_type_requirements')

	service_types = ServiceType.objects.all().order_by('name')
	requirements = Requirement.objects.all().order_by('name')

	return render(request, 'requirements/manage_service_type_requirements.html', {
		'service_types': service_types,
		'requirements': requirements,
	})


@login_required
@staff_member_required(login_url=None)
def service_type_requirements_ajax(request):
	"""
	Ajax endpoint. Expects GET param ?id=<service_type_id>.
	Returns JSON: { assigned: [ids], assigned_details: [{id,name}], all: [{id,name}] }
	"""
	st_id = request.GET.get('id')
	if not st_id:
		return JsonResponse({'error': 'missing id'}, status=400)

	service_type = get_object_or_404(ServiceType, id=st_id)
	assigned_qs = service_type.requirements.all().order_by('name')
	assigned = [r.id for r in assigned_qs]
	assigned_details = [{'id': r.id, 'name': r.name} for r in assigned_qs]

	all_reqs = Requirement.objects.all().order_by('name')
	all_details = [{'id': r.id, 'name': r.name} for r in all_reqs]

	return JsonResponse({
		'assigned': assigned,
		'assigned_details': assigned_details,
		'all': all_details,
	})