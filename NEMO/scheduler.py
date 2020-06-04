from datetime import datetime, timedelta
from schedule import Scheduler
import threading
import time

from NEMO.models import Interlock, Tool, UsageEvent, StaffCharge, AreaAccessRecord, ConsumableWithdraw, GlobalFlag

def pulse_interlocks():
	# print("pulse_interlocks() called")

	d = datetime.now()
	d1 = d - timedelta(minutes=1)
	i = 8

	while i < 21:

		t = datetime(d.year, d.month, d.day, i, 0, 0)
		if d1 < t < d:
			print("pulse_interlocks() called at " + str(d))

		i += 1

	tools = Tool.objects.all()
	for t in tools:
		if not t.in_use():
			if t.interlock is not None:
				t.interlock.pulse()
	#	else:
	#		print(t.name + " has been detected as being in use")


def daily_validate_transactions():
	print("Daily transaction validation started at " + str(datetime.now()))
	validation_date = datetime.now()-timedelta(days=5)
	print("Running validation for transactions older than " + str(validation_date))

	# validate usage events
	usage_events = UsageEvent.objects.filter(end__lte=validation_date, validated=False, contested=False)

	print("Found " + str(usage_events.count()) + " usage event transactions to validate.")

	for u in usage_events:
		u.auto_validate()

	# validate staff charges
	staff_charges = StaffCharge.objects.filter(end__lte=validation_date, validated=False, contested=False)

	print("Found " + str(staff_charges.count()) + " staff charge transactions to validate.")

	for s in staff_charges:
		s.auto_validate()

	# validate area access records
	area_access_records = AreaAccessRecord.objects.filter(end__lte=validation_date, validated=False, contested=False)

	print("Found " + str(area_access_records.count()) + " area access record transactions to validate.")

	for a in area_access_records:
		a.auto_validate()

	# validate consumable withdraws
	consumable_withdraws = ConsumableWithdraw.objects.filter(date__lte=validation_date, validated=False, contested=False)

	print("Found " + str(consumable_withdraws.count()) + " consumable withdraw transactions to validate.")

	for c in consumable_withdraws:
		c.auto_validate()

	print("Daily transaction validation completed at " + str(datetime.now()))


def print_status():
	print("schedule is running at " + str(datetime.now()))


def run_continuously(self, interval=1):
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

	scheduler = Scheduler()
	if scheduler is not None:
		print("start_scheduler called at " + dt_string)
		scheduler.every(1).minutes.do(pulse_interlocks)
		scheduler.every().day.at("22:00").do(daily_validate_transactions)
		scheduler.every(15).minutes.do(print_status)
		scheduler.run_continuously()

		flag = GlobalFlag.objects.get(name="SchedulerStarted")
		if flag is not None:
			flag.active = True
			flag.save()


def stop_scheduler():
	now = datetime.now()
	dt_string = now.strftime("%d/%m/%Y %H:%M:%S")

	print("stop_scheduler called at " + dt_string)



"""
def start_schedule():
	print("Starting schedule at " + str(datetime.now()))
	schedule.every(1).minutes.do(pulse_interlocks)
	schedule.every().day.at("22:00").do(daily_validate_transactions)
	schedule.every(15).minutes.do(print_status)

	while True:
		schedule.run_pending()
		time.sleep(1)
"""
