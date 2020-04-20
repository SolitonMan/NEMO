from datetime import datetime
from schedule import Scheduler
import threading
import time

from django.conf import settings
from NEMO.models import Interlock, Tool


def pulse_interlocks():
	# print("pulse_interlocks() called")
	tools = Tool.objects.all()
	for t in tools:
		if not t.in_use():
			if t.interlock is not None:
				t.interlock.pulse()
	#	else:
	#		print(t.name + " has been detected as being in use")


def run_continuously(self, interval=1):
	"""Continuously run, while executing pending jobs at each elapsed
	time interval.
	@return cease_continuous_run: threading.Event which can be set to
	cease continuous run.
	Please note that it is *intended behavior that run_continuously()
	does not run missed jobs*. For example, if you've registered a job
	that should run every minute and you set a continuous run interval
	of one hour then your job won't be run 60 times at each interval but
	only once.
	"""

	cease_continuous_run = threading.Event()

	class ScheduleThread(threading.Thread):

		@classmethod
		def run(cls):
			while not cease_continuous_run.is_set():
				self.run_pending()
				time.sleep(interval)

	continuous_thread = ScheduleThread()
	continuous_thread.setDaemon(True)
	continuous_thread.start()
	return cease_continuous_run

Scheduler.run_continuously = run_continuously


def start_scheduler():
	now = datetime.now()
	dt_string = now.strftime("%d/%m/%Y %H:%M:%S")

	if settings.SCHEDULED_JOBS_THREAD is None:
		print("start_scheduler called at " + dt_string)
		scheduler = Scheduler()
		scheduler.every(1).minutes.do(pulse_interlocks)
		settings.SCHEDULED_JOBS_THREAD = scheduler.run_continuously()
	else:
		print("start_scheduler already started when called at " + dt_string)

	if settings.SCHEDULED_JOBS_THREAD is None:
		print("Job scheduler failed to start at " + dt_string)
	else:
		print("Job scheduler is running at " + dt_string)


def stop_scheduler():
	now = datetime.now()
	dt_string = now.strftime("%d/%m/%Y %H:%M:%S")

	print("stop_scheduler called at " + dt_string)
	job_thread = settings.SCHEDULED_JOBS_THREAD
	if job_thread is not None:
		job_thread.set()
	settings.SCHEDULED_JOBS_THREAD = None
