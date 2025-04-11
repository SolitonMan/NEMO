from rest_framework.serializers import ModelSerializer

from NEMO.models import User, Project, Account, Reservation, AreaAccessRecord, UsageEvent, Task, TaskHistory, ScheduledOutage, Tool


class UserSerializer(ModelSerializer):
	class Meta:
		model = User
		fields = ['id','first_name','last_name','username','email']


class ProjectSerializer(ModelSerializer):
	class Meta:
		model = Project
		fields = ['id', 'name', 'application_identifier', 'active']


class AccountSerializer(ModelSerializer):
	class Meta:
		model = Account
		fields = ['id', 'name', 'active']


class ToolSerializer(ModelSerializer):
	primary_owner = UserSerializer(read_only=True)

	class Meta:
		model = Tool
		fields = ['id','name','primary_owner','location']


class ReservationSerializer(ModelSerializer):
	class Meta:
		model = Reservation
		fields = '__all__'


class UsageEventSerializer(ModelSerializer):
	projects = ProjectSerializer(many=True, read_only=True)
	customers = UserSerializer(many=True, read_only=True)
	tool = ToolSerializer(read_only=True)
	operator = UserSerializer(read_only=True)

	class Meta:
		model = UsageEvent
		fields = ['id','operator','start','end','user','tool','project','customers','projects']


class AreaAccessRecordSerializer(ModelSerializer):
	class Meta:
		model = AreaAccessRecord
		fields = '__all__'


class TaskHistorySerializer(ModelSerializer):
	class Meta:
		model = TaskHistory
		fields = '__all__'


class TaskSerializer(ModelSerializer):
	history = TaskHistorySerializer(many=True, read_only=True)

	class Meta:
		model = Task
		fields = '__all__'


class ScheduledOutageSerializer(ModelSerializer):
	class Meta:
		model = ScheduledOutage
		fields = '__all__'
