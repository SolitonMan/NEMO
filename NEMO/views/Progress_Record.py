from django.shortcuts import render
from NEMO.models import UserRequirementProgress
from django.contrib.auth.decorators import login_required

@login_required
def progress_record_view(request):
    progress_records = UserRequirementProgress.objects.filter(user=request.user)
    return render(request, 'progress_record.html', {'progress_records': progress_records})
