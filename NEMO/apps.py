from django.apps import AppConfig

class UsersConfig(AppConfig):
	name = 'NEMO'

	def ready(self):
		import NEMO.signals
