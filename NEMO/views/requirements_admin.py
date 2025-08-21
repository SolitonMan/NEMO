from datetime import timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.core.mail import send_mail
from django.shortcuts import render, redirect, get_object_or_404
from NEMO.models import Tool, Area, Requirement, ToolRequirement, AreaRequirement, UserRequirementProgress

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
	return render(request, 'requirements/add_requirement.html')

@staff_member_required(login_url=None)
def manage_requirements(request):
    tools = Tool.objects.all()
    areas = Area.objects.all()
    requirements = Requirement.objects.all()

    if request.method == "POST":
        # Handle tool requirements
        for tool in tools:
            req_ids = request.POST.getlist(f"tool_{tool.id}_requirements")
            ToolRequirement.objects.filter(tool=tool).exclude(requirement_id__in=req_ids).delete()
            for req_id in req_ids:
                ToolRequirement.objects.get_or_create(tool=tool, requirement_id=req_id)

        # Handle area requirements
        for area in areas:
            req_ids = request.POST.getlist(f"area_{area.id}_requirements")
            AreaRequirement.objects.filter(area=area).exclude(requirement_id__in=req_ids).delete()
            for req_id in req_ids:
                AreaRequirement.objects.get_or_create(area=area, requirement_id=req_id)

        return redirect('manage_requirements')

    # Prepare current assignments
    tool_requirements = {tool.id: set(ToolRequirement.objects.filter(tool=tool).values_list('requirement_id', flat=True)) for tool in tools}
    area_requirements = {area.id: set(AreaRequirement.objects.filter(area=area).values_list('requirement_id', flat=True)) for area in areas}

    return render(request, 'requirements/manage_requirements.html', {
        'tools': tools,
        'areas': areas,
        'requirements': requirements,
        'tool_requirements': tool_requirements,
        'area_requirements': area_requirements,
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