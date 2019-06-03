from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_GET
from django.http import HttpResponseRedirect

from NEMO.decorators import disable_session_expiry_refresh
from NEMO.views.status_dashboard import create_tool_summary
from NEMO.views.authentication import check_for_core


@login_required
@require_GET
@disable_session_expiry_refresh
def refresh_sidebar_icons(request):
	if check_for_core(request):
		return HttpResponseRedirect("/choose_core/")
	tool_summary = create_tool_summary()
	return render(request, 'refresh_sidebar_icons.html', {'tool_summary': tool_summary})
