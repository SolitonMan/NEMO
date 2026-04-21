from django.forms import Widget
from django.utils.safestring import mark_safe


class ToolTree(Widget):
	def render(self, name, value, attrs=None, renderer=None):
		"""
		This widget takes a list of tools and creates nested unordered lists in a hierarchical manner.
		The parameters name and attrs are not used.
		'value' is a dictionary which must contain a 'tools' key with a value that is a QuerySet of all tools to be put in the list.
		A collection of unordered HTML lists is returned with various callbacks and properties attached to each nested element.

		For a more concrete example, suppose the following tools are input to the tool tree:
		Packaging/Dicing Saw
		Chemical Vapor Deposition/PECVD
		Gen Furnaces/Sinter

		The following unordered HTML list would be produced:
		<ul>
			<li>
				<button class="tree-toggler nav-header" aria-expanded="false" aria-controls="category-Packaging">Packaging</button>
				<ul id="category-Packaging" class="collapsed" hidden>
					<li>
						<a href="javascript:void(0);" onclick="on_tool_tree_click($(this))" class="leaf node" data-tool-id="...">Dicing saw</a>
					</li>
				</ul>
			</li>
			...
		</ul>
		"""
		tree = ToolTreeHelper(None)
		for tool in value['tools']:
			tree.add(tool.category + '/' + tool.name, tool.id)
		return mark_safe(tree.render())


class ToolTreeHelper:
	"""
	This class reads in a textual representation of the organization of each laboratory tool and renders it to equivalent
	unordered HTML lists.
	"""
	def __init__(self, name):
		self.name = name
		self.children = []
		self.id = None

	def add(self, tool, identifier):
		"""
		This function takes as input a string representation of the tool in the organization hierarchy.
		Example input might be "Imaging and Analysis/Microscopes/Zeiss FIB". The input is parsed with '/' as the
		separator and the tool is added to the class' tree structure.
		"""
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
		"""
		This function cycles through the root node of the tool list and enumerates all the child nodes directly.
		The function assumes that a tree structure of the tools has already been created by calling 'add(...)' multiple
		times. A string of unordered HTML lists is returned.
		"""
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
		"""
		Recursively dive through the tree structure and convert it to unordered HTML lists.
		Each node is output as an HTML list item. If the node has children then those are also output.
		"""
		result += '<li>'
		if node.__is_leaf():
			result += (
				f'<a href="javascript:void(0);" style="display: inline;" '
				f'onclick="set_selected_item(this)" '
				f'class="leaf node" data-tool-id="{node.id}" data-type="tool link" '
				f'role="treeitem" tabindex="0" aria-label="{node.name}">{node.name}</a>'
			)
		else:
			# Use a button for toggling, with ARIA attributes for expand/collapse
			category_id = f"category-{self.__safe_id(node.name)}"
			result += (
				f'<button class="tree-toggler nav-header" aria-expanded="false" aria-controls="{category_id}" '
				f'onclick="toggle_tool_tree_category(this, \'{category_id}\')" '
				f'type="button" tabindex="0" aria-label="Expand/collapse {node.name}">{node.name}</button>'
				f'<ul id="{category_id}" class="nav nav-list tree" data-category="{node.name}" role="group" hidden>'
			)
			for child in node.children:
				result = self.__render_helper(child, result)
			result += '</ul>'
		result += '</li>'
		return result

	def __is_leaf(self):
		""" Test if this node is a leaf (i.e. an actual tool). If it is not then the node must be a tool category. """
		return self.children == []

	def __safe_id(self, name):
		""" Generate a safe HTML id from a category name. """
		return ''.join(c if c.isalnum() else '-' for c in name)

	def __str__(self):
		""" For debugging, output a string representation of the object in the form: <name [child1, child2, child3, ...]> """
		result = str(self.name)
		if not self.__is_leaf():
			result += ' [' + ', '.join(str(child) for child in self.children) + ']'
		return result