from django.forms import Widget
from django.utils.html import escape
from django.utils.safestring import mark_safe

class ConfigurationEditor(Widget):
	def render(self, name, value, attrs=None):
		result = ""
		for config in value["configurations"]:
			if config.consumable.all().count() > 0:
				# create the configuration choice for the consumable list
				result += self.__render_consumable(config, value["user"])
			else:
				current_settings = config.current_settings_as_list()
				if len(current_settings) == 1:
					result += self.__render_for_one(config, value["user"])
				else:
					result += self.__render_for_multiple(config, value["user"])
		return mark_safe(result)

	def __render_consumable(self, config, user):
		current_setting = config.current_settings
		if current_setting is None or current_setting == '':
			current_setting = 0
		current_setting = int(current_setting)
		tool = config.tool
		try:
			current_reservation = user.current_reservation_for_tool(tool)
			res_conf = current_reservation.reservationconfiguration_set.get(configuration=config)
			current_setting = int(res_conf.consumable.id)
			config.replace_current_setting(0, current_setting)
			config.save()
		except:
			pass
		result = "<p><label class='form-inline'>" + escape(config.name) + ": "
		if not config.tool.in_use():
			result += "<select class='form-control' style='width:300px; max-width:100%' onchange=\"on_change_configuration(" + str(config.id) + ", 0, this.value)\">"
			for c in config.consumable.all():
				result += "<option value=" + str(c.id)
				if c.id == current_setting:
					result += " selected"
				result += ">" + escape(c.name) + "</option>"
			result += "</select>"
		else:
			for c in config.consumable.all():
				if c.id == current_setting:
					result += escape(c.name)
		result += "</label></p>"
		return result

	def __render_for_one(self, config, user):
		current_setting = config.current_settings_as_list()[0]
		tool = config.tool
		try:
			current_reservation = user.current_reservation_for_tool(tool)
			res_conf = current_reservation.reservationconfiguration_set.get(configuration=config)
			current_setting = str(res_conf.setting)
			config.replace_current_setting(0, config.get_setting_id(current_setting))
			config.save()
		except:
			pass
		result = "<p><label class='form-inline'>" + escape(config.name) + ": "
		if not config.tool.in_use() and config.user_is_maintainer(user):
			result += "<select class='form-control' style='width:300px; max-width:100%' onchange=\"on_change_configuration(" + str(config.id) + ", 0, this.value)\">"
			for index, option in enumerate(config.available_settings_as_list()):
				result += "<option value=" + str(index)
				if option == current_setting:
					result += " selected"
				result += ">" + escape(option) + "</option>"
			result += "</select>"
		else:
			result += escape(current_setting)
		result += "</label></p>"
		return result

	def __render_for_multiple(self, config, user):
		result = "<p>" + escape(config.name) + ":<ul>"
		for setting_index, current_setting in enumerate(config.current_settings_as_list()):
			tool = config.tool
			try:
				current_reservation = user.current_reservation_for_tool(tool)
				res_conf = current_reservation.reservationconfiguration_set.get(configuration=config)
				current_setting = str(res_conf.setting)
			except:
				pass

			result += "<li>"
			if not config.tool.in_use() and config.user_is_maintainer(user):
				result += "<label class='form-inline'>" + escape(config.configurable_item_name) + " #" + str(setting_index + 1) + ": "
				result += "<select class='form-control' style='width:300px' onchange=\"on_change_configuration(" + str(config.id) + ", " + str(setting_index) + ", this.value)\">"
				for option_index, option in enumerate(config.available_settings_as_list()):
					result += "<option value=" + str(option_index)
					if option == current_setting:
						result += " selected"
					result += ">" + escape(option) + "</option>"
				result += "</select></label>"
			else:
				result += config.configurable_item_name + " #" + str(setting_index + 1) + ": " + escape(current_setting)
		result += "</ul></p>"
		return result
