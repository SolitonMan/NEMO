from _ssl import PROTOCOL_TLSv1_2, CERT_REQUIRED
from base64 import b64decode
from logging import exception, getLogger

from django.conf import settings
from django.contrib.auth import authenticate, login, REDIRECT_FIELD_NAME, logout
from django.contrib.auth.backends import RemoteUserBackend, ModelBackend
from django.http import HttpResponse, HttpResponseRedirect, HttpResponseForbidden
from django.shortcuts import render
from django.urls import reverse, resolve
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_GET
from ldap3 import Tls, Server, Connection, AUTO_BIND_TLS_BEFORE_BIND, SIMPLE
from ldap3.core.exceptions import LDAPBindError, LDAPExceptionError

from NEMO.models import User, Requirement, UserRequirementProgress
from NEMO.views.customization import get_media_file_contents

from microsoft_auth.models import MicrosoftAccount


class RemoteUserAuthenticationBackend(RemoteUserBackend):
	""" The web server performs Kerberos authentication and passes the user name in via the REMOTE_USER environment variable. """
	create_unknown_user = False

	def clean_username(self, username):
		"""
		User names arrive in the form user@DOMAIN.NAME.
		This function chops off Kerberos realm information (i.e. the '@' and everything after).
		"""
		return username.partition('@')[0]


class NginxKerberosAuthorizationHeaderAuthenticationBackend(ModelBackend):
	""" The web server performs Kerberos authentication and passes the user name in via the HTTP_AUTHORIZATION header. """

	def authenticate(self, request, username=None, password=None, **keyword_arguments):
		# Perform any custom security checks below.
		# Returning None blocks the user's access.
		username = self.clean_username(request.META.get('HTTP_AUTHORIZATION', None))
		logger = getLogger(__name__)

		# The user must exist in the database
		try:
			user = User.objects.get(username=username)
		except User.DoesNotExist:
			logger.warning(f"Username {username} attempted to authenticate with Kerberos via Nginx, but that username does not exist in the NEMO database. The user was denied access.")
			return None

		# The user must be marked active.
		if not user.is_active:
			logger.warning(f"User {username} successfully authenticated with Kerberos via Nginx, but that user is marked inactive in the NEMO database. The user was denied access.")
			return None

		# All security checks passed so let the user in.
		logger.debug(f"User {username} successfully authenticated with Kerberos via Nginx and was granted access to NEMO.")
		return user

	def clean_username(self, username):
		"""
		User names arrive encoded in base 64, similar to Basic authentication, but with a bogus password set (since .
		This function chops off Kerberos realm information (i.e. the '@' and everything after).
		"""
		if not username:
			return None
		pieces = username.split()
		if len(pieces) != 2:
			return None
		if pieces[0] != "Basic":
			return None
		return b64decode(pieces[1]).decode().partition(':')[0]


class LDAPAuthenticationBackend(ModelBackend):
	""" This class provides LDAP authentication against an LDAP or Active Directory server. """

	@method_decorator(sensitive_post_parameters('password'))
	def authenticate(self, request, username=None, password=None, **keyword_arguments):
		logger = getLogger(__name__)

		if not username or not password:
			return None

		# The user must exist in the database
		try:
			user = User.objects.get(username=username)
		except User.DoesNotExist:
			logger.warning(f"Username {username} attempted to authenticate with LDAP, but that username does not exist in the NEMO database. The user was denied access.")
			return None

		# The user must be marked active.
		if not user.is_active:
			logger.warning(f"User {username} successfully authenticated with LDAP, but that user is marked inactive in the NEMO database. The user was denied access.")
			return None

		for server in settings.LDAP_SERVERS:
			try:
				t = Tls(validate=CERT_REQUIRED, version=PROTOCOL_TLSv1_2, ca_certs_file=server['certificate'])
				s = Server(server['url'], port=636, use_ssl=True, tls=t)
				c = Connection(s, user='{}\\{}'.format(server['domain'], username), password=password, auto_bind=AUTO_BIND_TLS_BEFORE_BIND, authentication=SIMPLE)
				c.unbind()
				# At this point the user successfully authenticated to at least one LDAP server.
				return user
			except LDAPBindError as e:
				logger.warning(f"User {username} attempted to authenticate with LDAP, but entered an incorrect password. The user was denied access.")
				pass  # When this error is caught it means the username and password were invalid against the LDAP server.
			except LDAPExceptionError as e:
				exception(e)

		# The user did not successfully authenticate to any of the LDAP servers.
		return None


@require_http_methods(['GET', 'POST'])
@sensitive_post_parameters('password')
def login_user(request, context=None):
    if request.user.is_authenticated:
        # Already authenticated – honor next if valid, else landing
        next_page = request.GET.get(REDIRECT_FIELD_NAME, reverse('landing'))
        try:
            resolve(next_page)
        except:
            next_page = reverse('landing')
        return HttpResponseRedirect(next_page)

    dictionary = {
        'login_banner': get_media_file_contents('login_banner.html'),
        'user_name_or_password_incorrect': False,
    }

    if request.method == 'GET':
        return render(request, 'login.html', dictionary)

    username = request.POST.get('username', '')
    password = request.POST.get('password', '')
    user = authenticate(request, username=username, password=password)
    if not user or not user.is_active:
        dictionary['user_name_or_password_incorrect'] = True
        return render(request, 'login.html', dictionary)

    login(request, user)
    next_page = request.GET.get(REDIRECT_FIELD_NAME, reverse('landing'))
    initialize_user_session(request, user, next_page)
    try:
        resolve(next_page)
    except:
        next_page = reverse('landing')
    return HttpResponseRedirect(next_page)



@require_GET
def logout_user(request):
	logout(request)
	return HttpResponseRedirect(reverse('landing'))

@require_http_methods(['GET', 'POST'])
def choose_core(request):
	if request.method == "GET":
		# get the cores to which the user is associated
		dictionary = {
			'cores' : request.user.core_ids.all(),
		}
		return render(request, 'choose_core.html', dictionary)
	core_id = request.POST.get('core_id','')

	request.session['active_core'] = request.user.core_ids.values_list('name', flat=True).get(id=core_id)

	request.session['active_core_id'] = core_id
	next_page = reverse('landing')
	return HttpResponseRedirect(next_page)

def check_for_core(request):
	has_core = request.session.get('has_core')
	if has_core != "None":  #None would indicate the value isn't set per session.get()
		if str(has_core) == "true":
			active_core = request.session.get('active_core')	
			if active_core == "":
				return True
			else:
				return False
		return False
	return False


def csrf_failure(request, reason=""):
	response = HttpResponseForbidden()

	msg = "<h1>CSRF Failure</h1>"

	msg += "<br/><br/>"
	msg += "Form Data: <br/>" 
	msg += str(list(request.POST.items()))
	msg += str(list(request.META.items()))

	response.write(msg)

	return response 


def initialize_user_session(request, user, next_page):
	# Requirements check
	requirements = Requirement.objects.filter(login_requirement_flag=True)
	user_requirements = UserRequirementProgress.objects.filter(user=user)
	if user_requirements.count() > 0:
		# existing user so do nothing with next page
		pass
	else:
		next_page = reverse('user_requirements')
		for requirement in requirements:
			UserRequirementProgress.objects.create(user=user, requirement=requirement, status='not_started', updated=timezone.now())

	# Group flags
	flags = {
		"administrative_staff": user.groups.filter(name="Administrative Staff").exists(),
		"core_admin": user.groups.filter(name="Core Admin").exists(),
		"financial_admin": user.groups.filter(name="Financial Admin").exists(),
		"pi": user.groups.filter(name="PI").exists(),
		"technical_staff": user.groups.filter(name="Technical Staff").exists(),
	}
	request.session.update(flags)

	# Core relationships
	cores = list(user.core_ids.values_list('name', 'id'))
	if not cores:
		request.session.update({
			"active_core": "none",
			"active_core_id": 0,
			"has_core": "false",
		})
	elif len(cores) == 1:
		name, cid = cores[0]
		request.session.update({
			"active_core": name,
			"active_core_id": cid,
			"has_core": "true",
		})
	else:
		names = ",".join([c[0] for c in cores]) + ","
		ids = ",".join([str(c[1]) for c in cores]) + ","
		request.session.update({
			"active_core": names,
			"active_core_id": ids,
			"has_core": "true",
		})