from django.urls import reverse
from django.conf import settings

def custom_microsoft(request):
	"""
	Custom context processor to override the Microsoft authorization URL
	and always include the desired 'next' parameter.
	"""
	context = {}
	# Only add if Microsoft login is enabled
	microsoft_login_enabled = getattr(settings, "MICROSOFT_AUTH_ENABLED", True)
	context["microsoft_login_enabled"] = microsoft_login_enabled

	if microsoft_login_enabled:
		# Always set next to your post-login redirect view
		next_url = reverse("post_login_redirect")
		authorization_url = reverse("microsoft_auth:to-auth-redirect") + f"?next={next_url}"
		context["microsoft_authorization_url"] = authorization_url

	return context

def show_logout_button(request):
	return {'logout_allowed': True}


def hide_logout_button(request):
	return {'logout_allowed': False}


def device(request):
	return {'device': request.device}
