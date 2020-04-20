from _ssl import PROTOCOL_TLSv1_2, CERT_REQUIRED
from base64 import b64decode
from logging import exception, getLogger

from django.conf import settings
from django.contrib.auth import authenticate, login, REDIRECT_FIELD_NAME, logout
from django.contrib.auth.backends import RemoteUserBackend, ModelBackend
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse, resolve
from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_GET
from ldap3 import Tls, Server, Connection, AUTO_BIND_TLS_BEFORE_BIND, SIMPLE
from ldap3.core.exceptions import LDAPBindError, LDAPExceptionError

from NEMO.models import User
from NEMO.views.customization import get_media_file_contents


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
def login_user(request):
	request.session['has_core'] = False
	if 'NEMO.views.authentication.RemoteUserAuthenticationBackend' in settings.AUTHENTICATION_BACKENDS or 'NEMO.views.authentication.NginxKerberosAuthorizationHeaderAuthenticationBackend' in settings.AUTHENTICATION_BACKENDS:
		if request.user.is_authenticated:
			return HttpResponseRedirect(reverse('landing'))
		else:
			return render(request, 'authorization_failed.html')

	dictionary = {
		'login_banner': get_media_file_contents('login_banner.html'),
		'user_name_or_password_incorrect': False,
	}
	if request.method == 'GET':
		return render(request, 'login.html', dictionary)
	username = request.POST.get('username', '')
	password = request.POST.get('password', '')
	user = authenticate(request, username=username, password=password)
	if user:
		login(request, user)
		try:

			# check for group affiliations and set flags
			if user.groups.filter(name="Administrative Staff").exists():
				request.session['administrative_staff'] = True
			else:
				request.session['administrative_staff'] = False

			if user.groups.filter(name="Core Admin").exists():
				request.session['core_admin'] = True
			else:
				request.session['core_admin'] = False

			if user.groups.filter(name="Financial Admin").exists():
				request.session['financial_admin'] = True
			else:
				request.session['financial_admin'] = False

			if user.groups.filter(name="PI").exists():
				request.session['pi'] = True
			else:
				request.session['pi'] = False

			if user.groups.filter(name="Technical Staff").exists():
				request.session['technical_staff'] = True
			else:
				request.session['technical_staff'] = False

			# check for a Core relationship for the user
			count = user.core_ids.all().count()
			if count == 0:
				# send the user to the landing page; no Core relationship exists
				request.session['active_core'] = "none"
				request.session['active_core_id'] = 0
				request.session['has_core'] = "false"
				next_page = request.GET[REDIRECT_FIELD_NAME]

			if count == 1:
				# set the Core to the relevant option then redirect to the landing page
				request.session['active_core'] = request.user.core_ids.values_list('name', flat=True).get()
				request.session['active_core_id'] = request.user.core_ids.values_list('id', flat=True).get()
				request.session['has_core'] = "true"
				next_page = request.GET[REDIRECT_FIELD_NAME]

			if count > 1:
				request.session['has_core'] = "true"
				names = request.user.core_ids.values_list('name', flat=True)
				ids = request.user.core_ids.values_list('id', flat=True)
				active_core = ""
				active_core_ids = ""

				for n in enumerate(names):
					active_core = active_core + str(n[1]) + ","

				for i in enumerate(ids):
					active_core_ids = active_core_ids + str(i[1]) + ","


				request.session['active_core'] = str(active_core)
				request.session['active_core_id'] = str(active_core_ids)

				next_page = request.GET[REDIRECT_FIELD_NAME]

			resolve(next_page)  # Make sure the next page is a legitimate URL for NEMO
		except:
			next_page = reverse('landing')
		return HttpResponseRedirect(next_page)
	dictionary['user_name_or_password_incorrect'] = True
	return render(request, 'login.html', dictionary)


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
