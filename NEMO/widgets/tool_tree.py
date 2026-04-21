from django.forms import Widget
from django.utils.safestring import mark_safe


class ToolTree(Widget):
	def render(self, name, value, attrs=None, renderer=None):
		"""
		This widget takes a list of tools and creates nested unordered lists in a hierarchical manner.
		"""
		tree = ToolTreeHelper(None)
		for tool in value['tools']:
			tree.add(tool.category + '/' + tool.name, tool.id)
		return mark_safe(tree.render())


class ToolTreeHelper:
	def __init__(self, name):
		self.name = name
		self.children = []
		self.id = None

	def add(self, tool, identifier):
		part = tool.partition('/')
		for child in self.children:
			if child.name == part[0]:
				child.add(part[2], identifier)
				return
		self.children.append(ToolTreeHelper(part[0]))
		if part[2] != '':
			self.children[-1].add(part[2], identifier)
		else:
			self.children[-1].id = identifier

	def render(self):
		result = (
			'<nav class="nav nav-list" style="border: solid 1px grey; background-color:#f0f0f0; padding: 3px; width: 95%;" aria-label="Tool tree navigation">'
			'Current tool:<div id="current_tool_selection" style="font-weight: bold; color: green;" aria-live="polite"></div>'
			'</nav>'
			'<hr/>'
			'<div class="tool_tree_scrolling" role="region" aria-label="Tool tree">'
			'<ul class="nav nav-list" id="tool_tree" style="display:none">'
		)
		for child in self.children:
			result += self.__render_helper(child, '')
		result += '</ul></div>'
		return result

	def __render_helper(self, node, result):
		result += '<li>'
		if node.__is_leaf():
			result += (
				f'<a href="javascript:void(0);" style="display: inline;" '
				f'onclick="set_selected_item(this)" '
				f'class="leaf node" data-tool-id="{node.id}" data-type="tool link" '
				f'role="treeitem" tabindex="0" aria-label="{node.name}">{node.name}</a>'
			)
		else:
			category_id = f"category-{self.__safe_id(node.name)}"
			result += (
				f'<button class="tree-toggler nav-header btn btn-link" aria-expanded="false" aria-controls="{category_id}" '
				f'onclick="toggle_tool_tree_category(this, \'{category_id}\')" '
				f'type="button" tabindex="0" aria-label="Expand/collapse {node.name}">'
				f'<span class="glyphicon glyphicon-chevron-right" aria-hidden="true"></span> '
				f'{node.name}'
				f'</button>'
				f'<ul id="{category_id}" class="nav nav-list tree collapsed" data-category="{node.name}" role="group" style="display:none">'
			)
			for child in node.children:
				result = self.__render_helper(child, result)
			result += '</ul>'
		result += '</li>'
		return result

	def __is_leaf(self):
		return self.children == []

	def __safe_id(self, name):
		return ''.join(c if c.isalnum() else '-' for c in name)

	def __str__(self):
		result = str(self.name)
		if not self.__is_leaf():
			result += ' [' + ', '.join(str(child) for child in self.children) + ']'
		return result