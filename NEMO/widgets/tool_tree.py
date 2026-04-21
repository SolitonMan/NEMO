from django.forms import Widget
from django.utils.safestring import mark_safe


class ToolTree(Widget):
	def render(self, name, value, attrs=None, renderer=None, selected_tool_id=None):
		"""
		This widget takes a list of tools and creates nested unordered lists in a hierarchical manner.
		'value' is a dictionary which must contain a 'tools' key with a value that is a QuerySet of all tools to be put in the list.
		'selected_tool_id' is the id of the currently selected tool, used for highlighting and expanding.
		"""
		tree = ToolTreeHelper(None)
		for tool in value['tools']:
			tree.add(tool.category + '/' + tool.name, tool.id)
		return mark_safe(tree.render(selected_tool_id))


class ToolTreeHelper:
	def __init__(self, name):
		self.name = name
		self.children = []
		self.id = None
		self.parent = None  # Track parent for expansion

	def add(self, tool, identifier):
		part = tool.partition('/')
		for child in self.children:
			if child.name == part[0]:
				child.add(part[2], identifier)
				return
		new_child = ToolTreeHelper(part[0])
		new_child.parent = self
		self.children.append(new_child)
		if part[2] != '':
			self.children[-1].add(part[2], identifier)
		else:
			self.children[-1].id = identifier

	def render(self, selected_tool_id=None):
		# Find the path to the selected tool for expansion
		selected_path = self._find_selected_path(selected_tool_id)
		result = (
			'<nav class="nav nav-list" style="border: solid 1px grey; background-color:#f0f0f0; padding: 3px; width: 95%;" aria-label="Tool tree navigation">'
			'Current tool:<div id="current_tool_selection" style="font-weight: bold; color: green;" aria-live="polite"></div>'
			'</nav>'
			'<hr/>'
			'<div class="tool_tree_scrolling" role="region" aria-label="Tool tree">'
			'<ul class="nav nav-list" id="tool_tree" style="display:none">'
		)
		for child in self.children:
			result += self.__render_helper(child, '', selected_tool_id, selected_path)
		result += '</ul></div>'
		return result

	def __render_helper(self, node, result, selected_tool_id, selected_path):
		result += '<li>'
		if node.__is_leaf():
			is_selected = str(node.id) == str(selected_tool_id)
			aria_current = ' aria-current="true"' if is_selected else ''
			result += (
				f'<a href="javascript:void(0);" style="display: inline;" '
				f'onclick="set_selected_item(this)" '
				f'class="leaf node{" selected" if is_selected else ""}" data-tool-id="{node.id}" data-type="tool link" '
				f'role="treeitem" tabindex="0" aria-label="{node.name}"{aria_current}>{node.name}</a>'
			)
		else:
			category_id = f"category-{self.__safe_id(node.name)}"
			# Determine if this category should be expanded
			should_expand = selected_path and node in selected_path
			aria_expanded = 'true' if should_expand else 'false'
			ul_class = "nav nav-list tree expanded" if should_expand else "nav nav-list tree collapsed"
			ul_style = "display:block" if should_expand else "display:none"
			icon_class = "glyphicon glyphicon-chevron-down" if should_expand else "glyphicon glyphicon-chevron-right"
			onclick = f"toggle_tool_tree_category(this, '{category_id}')"
			result += (
				f'<button class="tree-toggler nav-header btn btn-link" aria-expanded="{aria_expanded}" aria-controls="{category_id}" '
				f'onclick="{onclick}" '
				f'type="button" tabindex="0" aria-label="Expand/collapse {node.name}">'
				f'<span class="{icon_class}" aria-hidden="true"></span> '
				f'{node.name}'
				f'</button>'
				f'<ul id="{category_id}" class="{ul_class}" data-category="{node.name}" role="group" style="{ul_style}">'
			)
			for child in node.children:
				result = self.__render_helper(child, result, selected_tool_id, selected_path)
			result += '</ul>'
		result += '</li>'
		return result

	def __is_leaf(self):
		return self.children == []

	def __safe_id(self, name):
		return ''.join(c if c.isalnum() else '-' for c in name)

	def _find_selected_path(self, selected_tool_id):
		"""
		Returns a list of nodes from root to the selected tool node, or None if not found.
		"""
		if selected_tool_id is None:
			return None
		path = []
		if self._find_path_helper(selected_tool_id, path):
			return path
		return None

	def _find_path_helper(self, selected_tool_id, path):
		if str(self.id) == str(selected_tool_id):
			path.insert(0, self)
			return True
		for child in self.children:
			if child._find_path_helper(selected_tool_id, path):
				path.insert(0, self)
				return True
		return False

	def __str__(self):
		result = str(self.name)
		if not self.__is_leaf():
			result += ' [' + ', '.join(str(child) for child in self.children) + ']'
		return result